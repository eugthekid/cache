"""
retailers.py
------------
Turns whatever a source called the store into one canonical retailer.

WHY: the same shop arrives spelled several ways depending on which bot
reported it -- measured in real data, Pokemon Center appeared as both
"https://www.pokemoncenter.com" (410 orders) and "PokemonCenter.com",
while Target and StockX arrive as bare names with no URL at all. Grouping
or filtering on the raw string therefore splits one retailer into several.

Same discipline as products.py: DETERMINISTIC normalization only. A URL is
reduced to its registrable domain; a bare name is slugified. Nothing is
fuzzy-matched, because a wrong merge here silently misattributes spend.

DISPLAY_NAMES is a small hand-maintained map from key -> the name a person
would actually write. An unknown retailer is not a failure: it falls back
to the domain (or the original text), which is already readable.
"""

import re
from typing import Optional
from urllib.parse import urlparse

# Multi-label public suffixes we actually encounter. Without these,
# "amazon.co.uk" would reduce to the meaningless "co.uk".
_MULTI_PART_TLDS = {
    "co.uk", "co.jp", "com.au", "co.nz", "com.br", "co.kr", "com.mx",
}

DISPLAY_NAMES = {
    "pokemoncenter.com": "Pokémon Center",
    "crunchyroll.com": "Crunchyroll",
    "target.com": "Target",
    "target": "Target",
    "bestbuy.com": "Best Buy",
    "walmart.com": "Walmart",
    "samsclub.com": "Sam's Club",
    "costco.com": "Costco",
    "gamestop.com": "GameStop",
    "kith.com": "Kith",
    "stockx.com": "StockX",
    "stockx": "StockX",
    "goat.com": "GOAT",
    "nike.com": "Nike",
    "nike-snkrs": "Nike SNKRS",
    "snkrs": "Nike SNKRS",
    "adidas.com": "Adidas",
    "shopify.com": "Shopify",
    "amazon.com": "Amazon",
    "nyc.gov": "NYC City Store",
}


def _registrable_domain(host: str) -> str:
    """example.com from www.store.example.com. Subdomains are dropped on
    purpose: store.crunchyroll.com and crunchyroll.com are one retailer."""
    host = host.lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_PART_TLDS and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def normalize_key(site: Optional[str]) -> Optional[str]:
    """Stable identity for a retailer. Same input -> same key, always."""
    if not site or not str(site).strip():
        return None
    text = str(site).strip()

    if "://" in text or text.lower().startswith("www."):
        parsed = urlparse(text if "://" in text else f"https://{text}")
        host = parsed.netloc or parsed.path.split("/")[0]
        if host:
            return _registrable_domain(host)

    # Bare text that still looks like a domain ("PokemonCenter.com").
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
        return _registrable_domain(text)

    # A plain name ("Nike SNKRS") -> a slug ("nike-snkrs").
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or None


def display_name(site: Optional[str]) -> Optional[str]:
    """What the UI shows. Falls back to the key, then the original text --
    an unmapped retailer still reads fine, it just isn't prettified."""
    key = normalize_key(site)
    if key is None:
        return None
    if key in DISPLAY_NAMES:
        return DISPLAY_NAMES[key]
    if "." in key:
        return key
    return str(site).strip()
