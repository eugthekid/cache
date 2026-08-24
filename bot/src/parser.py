"""
parser.py
---------
Turns a Discord message (with its embed) into a plain dictionary matching
inventory-tracker's OrderCreate schema.

Ported from discord-checkout-tracker's src/parser.py: the field-cleaning
helpers (_clean_value, _parse_money, _extract_markdown_link, FIELD_MAP,
FAILURE_KEYWORDS, _looks_greenish) are UNCHANGED -- those solve "how do I
read a value out of an embed field cleanly," which hasn't changed.

What's genuinely different: discord-checkout-tracker's looks_like_checkout()
was a boolean accept/reject gate -- only successes were ever stored, and a
failure/cancellation was silently dropped. inventory-tracker tracks every
checkout ATTEMPT (see docs/DATA-MODEL.md), so the old gate is replaced here
by classify_checkout(), which returns a (status, failure_reason) pair for
success, failure, AND cancellation instead of just filtering failures out.
"""

import html
import re
from typing import Any, Optional

FIELD_MAP = {
    "Module": "module",
    "Mode": "mode",
    "Site": "site",
    "Size": "size",
    "Quantity": "quantity",
    "Total": "total",
    "Price": "total",                 # Refract
    "ID": "checkout_id",
    "Delivery": "delivery",
    "Profile": "profile",
    "Profile Name": "profile",        # HayhaAIO
    "Payment": "payment",
    "Proxy Group": "proxy_group",
    "Order #": "order_number",
    "Order Number": "order_number",   # HayhaAIO
    "Order ID": "order_number",       # Shikari
    "Order URL": "order_url",
    "Is Preorder": "is_preorder",
    "Item": "product",                # HayhaAIO's item-name field
    "Product": "product",             # Refract
}

# Field names that, when found on the embed, are a strong structural signal
# that this is a checkout card at all -- regardless of what its title says.
# Used by classify_checkout() as a fallback when the text alone is
# ambiguous (see _looks_checkout_shaped).
_CHECKOUT_FIELD_NAMES = {
    "module", "site", "profile", "profile name",
    "order #", "order number", "order id", "total",
}

FAILURE_KEYWORDS = (
    "cancel", "declined", "failed", "denied", "error",
    "unsuccessful", "out of stock", "sold out", "fraud",
)


def _clean_value(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    cleaned = html.unescape(text.strip())
    if cleaned.startswith("||") and cleaned.endswith("||"):
        cleaned = cleaned[2:-2].strip()
    return cleaned


def _parse_money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"\d+\.?\d*", text.replace(",", ""))
    return float(match.group()) if match else None


def _extract_price_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"\$[\d,]+\.?\d*", text)
    return match.group() if match else None


def _extract_markdown_link(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not text:
        return text, None
    match = re.match(r"^\[(.+)\]\((\S+)\)$", text.strip())
    if not match:
        return text, None
    label = match.group(1).strip("*").strip()
    return label, match.group(2)


_QTY_PREFIX_RE = re.compile(r"^\s*(\d+)\s*x\s+", re.IGNORECASE)
_TRAILING_PRICE_RE = re.compile(r"\s*[-–—]\s*\$?[\d,]+\.?\d*\s*(?:USD|CAD|GBP|EUR)?\s*(?:\([^)]*\))?\s*$", re.IGNORECASE)


def _clean_product_text(text: Optional[str]) -> Optional[str]:
    """
    Strip the packaging different bots wrap around the same product name,
    so the SAME item reads identically no matter which bot reported it.
    Two patterns, both seen in real data:

      HiddenAIO : "1x Pokémon TCG: Foo (36 Packs) - 161.64 USD (OS)"
      HayhaAIO  : "Pokémon TCG: Foo - $35.98"
      wanted    : "Pokémon TCG: Foo (36 Packs)" / "Pokémon TCG: Foo"

    The leading "Nx" is pure redundancy -- it always agreed with the
    embed's own Quantity field across every order checked -- and the
    trailing price is already captured as unit_price, so leaving either in
    the name only creates phantom "different products" when grouping.

    Deliberately conservative: only a price at the very END is removed, so
    a name that legitimately contains a number or a dash ("Series 3",
    "Scarlet & Violet-Prismatic") is untouched.
    """
    if not text:
        return text
    cleaned = _QTY_PREFIX_RE.sub("", text)
    cleaned = _TRAILING_PRICE_RE.sub("", cleaned)
    return cleaned.strip() or text.strip()


def _parse_quantity(text: Optional[str]) -> Optional[int]:
    """The embed's Quantity field is text ("1", "2x", ...); OrderCreate
    wants a real int. Falls back to 1 -- absent-or-unparseable quantity
    should never mean "zero units," it means "assume one," since that's
    what every checkout actually is at minimum."""
    if not text:
        return 1
    match = re.search(r"\d+", text)
    return int(match.group()) if match else 1


def _looks_greenish(color: Any) -> bool:
    if color is None:
        return False
    r, g, b = (color.r, color.g, color.b) if hasattr(color, "r") else color
    return g > r + 30 and g > b + 30


def _failure_field(embed: Any) -> Optional[tuple[str, str]]:
    """
    Returns (status, reason_text) for the first "*Reason" field found (e.g.
    "Cancel Reason", "Decline Reason", "Fraud Reason" -- HayhaAIO's pattern),
    or None if there isn't one.

    The status comes from the FIELD NAME, not the reason text: "Cancel
    Reason" always means cancelled, any other "*Reason" field means failed
    -- because the reason's own text might not contain an obvious keyword
    at all (e.g. "Payment method expired" doesn't say "cancel" or "fail").
    """
    for field in getattr(embed, "fields", None) or []:
        name = (getattr(field, "name", "") or "").strip().lower()
        if name.endswith("reason"):
            status = "cancelled" if "cancel" in name else "failed"
            return status, _clean_value(field.value)
    return None


def _looks_checkout_shaped(embed: Any, fields_present: set[str]) -> bool:
    """
    Structural fallback for classify_checkout()'s initial gate: does this
    embed have at least two of the field names real checkout bots use?
    Needed because a card can be checkout-shaped without any success or
    failure WORD appearing anywhere -- an ambiguous title/description
    shouldn't fall through to "not a checkout at all" just because the text
    signal was inconclusive; that's what the field-shape signal is for.
    """
    return len(fields_present & _CHECKOUT_FIELD_NAMES) >= 2


def classify_checkout(embed: Any, keyword: str) -> Optional[tuple[str, Optional[str]]]:
    """
    Classify a checkout-attempt embed. Returns (status, failure_reason), or
    None if this embed isn't a checkout card at all (some unrelated message
    posted in the same channel).

    Signals, in priority order (same ordering discord-checkout-tracker used,
    extended to classify outcome instead of just gating on it):
      1. A "*Reason" field (e.g. HayhaAIO's "Cancel Reason") always wins,
         even over a misleading title -- HayhaAIO labels EVERY card
         "Successful Checkout!" regardless of the real outcome, and only
         reveals a cancellation through this extra field.
      2. A failure keyword in the author/title/description -- "cancel" maps
         to status='cancelled', everything else in FAILURE_KEYWORDS to
         status='failed'. The embed's own title is used as the reason text
         when there's no explicit reason field, since it's usually the most
         specific text available (e.g. "Order Canceled: Quantity Limit").
      3. The success keyword in the text -> status='success'.
      4. Neither text signal fired -- fall back to the embed's side-bar
         color (green -> success). This only runs after step 0 below has
         already confirmed the embed is checkout-shaped at all, so an
         ambiguous-and-not-green card is classified 'failed' (something on
         it did say "checkout"; we just can't tell you why it didn't work)
         rather than silently dropped.

    Step 0, before any of the above: is this even a checkout card? Text
    mentioning success/failure counts, and so does having the structural
    shape of one (see _looks_checkout_shaped) -- that second path matters
    because HayhaAIO's misleading-title problem means text alone isn't
    always trustworthy in either direction.
    """
    parts = [
        getattr(getattr(embed, "author", None), "name", "") or "",
        embed.title or "",
        embed.description or "",
    ]
    haystack = " ".join(parts).lower()
    fields_present = {
        (getattr(f, "name", "") or "").strip().lower()
        for f in getattr(embed, "fields", None) or []
    }

    has_success_word = keyword.lower() in haystack
    matched_failure_word = next((w for w in FAILURE_KEYWORDS if w in haystack), None)
    failure_field = _failure_field(embed)

    is_checkout_shaped = (
        has_success_word
        or matched_failure_word is not None
        or failure_field is not None
        or _looks_checkout_shaped(embed, fields_present)
    )
    if not is_checkout_shaped:
        return None

    if failure_field is not None:
        return failure_field

    if matched_failure_word is not None:
        status = "cancelled" if matched_failure_word == "cancel" else "failed"
        reason = embed.title or matched_failure_word.capitalize()
        return status, reason

    if has_success_word:
        return "success", None

    return ("success", None) if _looks_greenish(getattr(embed, "color", None)) else ("failed", None)


# Rough, overridable guess at product category from the parsed product
# text -- there's no reliable structured signal for this on the embed
# (see the `category` column's docstring in backend/app/models.py: it's
# free text, "set by hand or guessed by the ingestion layer"). Keep this
# list short and easy to extend rather than trying to be exhaustive; a
# wrong guess costs the user one click to correct in the Orders screen,
# so it's fine to be approximate.
_CATEGORY_HINTS = {
    "Sneakers": ("jordan", "nike", "yeezy", "dunk", "new balance", "adidas", "sneaker"),
    "Pokémon TCG": ("pokemon", "pokémon", "tcg", "booster", "elite trainer"),
}


def _guess_category(product_text: Optional[str]) -> Optional[str]:
    if not product_text:
        return None
    haystack = product_text.lower()
    for category, hints in _CATEGORY_HINTS.items():
        if any(hint in haystack for hint in hints):
            return category
    return None


def parse_message(message: Any) -> Optional[dict[str, Any]]:
    """
    Convert a discord.Message into a dict shaped like OrderCreate, or None
    if the message has no embed / doesn't look like a checkout card at all.
    Unlike discord-checkout-tracker's version, this ALWAYS returns a record
    for a checkout-shaped embed regardless of outcome -- status classification
    happens here via classify_checkout(), not as a separate accept/reject
    step before parsing.
    """
    if not message.embeds:
        return None

    embed = message.embeds[0]
    classification = classify_checkout(embed, keyword="success")
    if classification is None:
        return None
    status, failure_reason = classification

    channel = getattr(message, "channel", None)

    raw_description = (embed.description or "").lstrip("• ").strip() or None
    description_label, product_url = _extract_markdown_link(raw_description)

    fields: dict[str, Any] = {}
    extra_fields: dict[str, str] = {}
    for field in embed.fields:
        value = _clean_value(field.value)
        column = FIELD_MAP.get(field.name)
        if column:
            # Shikari markdown-links the PRODUCT NAME in the embed description
            # ("[**Foo**](url)"), handled above via description_label/
            # product_url. Refract does the same thing but inside a labeled
            # field instead ("Product": "[Foo](url)", "Order #":
            # "[#123](url)") -- so every mapped field gets the same
            # link-stripping, not just the description, or a bot like that
            # would store "[text](url)" verbatim in order_number/product.
            label, url = _extract_markdown_link(value)
            fields[column] = label
            if column == "product" and url and not product_url:
                product_url = url
        else:
            extra_fields[field.name] = value

    if product_url:
        extra_fields["Product URL"] = product_url

    raw_product = fields.get("product") or description_label
    # Order matters: the price and the quantity both have to be read OUT of
    # the raw text before _clean_product_text strips them from it.
    total_text = fields.get("total") or _extract_price_from_text(raw_product)
    total_amount = _parse_money(total_text)

    if fields.get("quantity"):
        quantity = _parse_quantity(fields.get("quantity"))
    else:
        # No Quantity field (some bots omit it) -- fall back to the "2x"
        # prefix in the product text, which is the only quantity signal
        # left. Defaults to 1 via _parse_quantity when neither exists.
        prefix_match = _QTY_PREFIX_RE.match(raw_product or "")
        quantity = int(prefix_match.group(1)) if prefix_match else 1

    product_text = _clean_product_text(raw_product)
    # unit_price, not total: OrderCreate.unit_price * quantity is how spend
    # and per-unit cost_basis are computed downstream (see crud.create_order
    # and dashboard.py) -- dividing here, once, means every consumer of
    # unit_price can assume it's genuinely per-unit.
    unit_price = (total_amount / quantity) if (total_amount and quantity) else total_amount

    return {
        "external_id": str(message.id),
        "status": status,
        "failure_reason": failure_reason,
        "raw_product_text": product_text,
        "profile": fields.get("profile"),
        "site": fields.get("site"),
        "module": fields.get("module"),
        "category": _guess_category(product_text),
        "quantity": quantity,
        "unit_price": unit_price,
        "order_number": fields.get("order_number"),
        "order_url": fields.get("order_url"),
        "purchased_at": message.created_at.isoformat(),
        "raw_json": {
            **fields,
            "product": product_text,
            "extra_fields": extra_fields,
            "channel_id": str(getattr(channel, "id", "")) or None,
            "channel_name": getattr(channel, "name", None),
        },
    }
