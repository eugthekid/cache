"""
classify.py
-----------
Identifies which retailer an email is from and what kind of update it
carries, from the SUBJECT LINE alone -- never the sender address.

WHY NOT SENDER: verified directly against real mail (see
docs/RECONNAISSANCE.md) that Target routes every checkout through a
per-order masked relay identity -- the sender arrives as something like
"orders_at_oe1_target_com_d6s3b4nf68x7g7_228k5870@icloud.com" (an encoded
"orders@oe1.target.com"), different on almost every message, and never
resolvable back to "target.com" by app.retailers.py's domain logic (that
function was checked directly: it would read this sender as icloud.com).
Subject lines are retailer-authored marketing/transactional copy and
survive the masking completely untouched, so they are the only reliable
classifier.

Every pattern below is matched against a REAL subject line pulled from the
connected inbox before being written here -- see the comment above each
retailer's block for which order/thread it came from. Nothing here is
guessed.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Retailer(str, Enum):
    POKEMON_CENTER = "pokemoncenter.com"
    TARGET = "target.com"
    WALMART = "walmart.com"


class EmailKind(str, Enum):
    CONFIRMATION = "confirmation"
    SHIPPED = "shipped"
    ARRIVED = "arrived"
    CANCELLED_FULL = "cancelled_full"
    CANCELLED_PARTIAL = "cancelled_partial"
    PAYMENT_PENDING = "payment_pending"  # preorder "we'll charge you soon" -- not an order event
    UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class Classification:
    # None only for EmailKind.UNRECOGNIZED -- every recognized subject
    # pattern is retailer-specific by construction, so a real retailer is
    # always known the moment kind is not UNRECOGNIZED.
    retailer: Optional[Retailer]
    kind: EmailKind
    # The order number extracted directly from the subject, when the
    # template carries one. None for kinds where it doesn't (rare) --
    # callers should fall back to scanning the body.
    order_number: Optional[str]


# --- Pokémon Center -------------------------------------------------------
# Real subjects observed (thread 19f675e3a4060d74, 19f6bbe0ad6c1533,
# 1a07c77cd70be10f):
#   "Thank you for shopping at PokemonCenter.com!"
#   "Your Pokémon Center order is on its way!"
#   "Your order has been canceled"
# PC's cancellation subject carries NO order number -- it's in the body
# ("Order Number: P0038875758"), unlike every other template here.
_PC_CONFIRM = re.compile(r"thank you for shopping at pokemoncenter\.com", re.I)
_PC_SHIPPED = re.compile(r"pok[eé]mon center order is on its way", re.I)
_PC_CANCELLED = re.compile(r"your order has been canceled", re.I)

# --- Target ----------------------------------------------------------------
# Real subjects observed across ~90 masked-identity profiles (verified
# across the full 183-order-number sweep, 2026-09-16):
#   "Thanks for shopping with us! Here's your order #:912003448396552."
#   "Get ready for something special! Items from order #NNN are about to ship."
#   "Your order arrives today! Order #NNN" / "...arrives tomorrow! Order #NNN"
#   "Items have arrived from order #NNN!"
#   "Sorry, we had to cancel order #NNN."
#   "You've successfully canceled items from your order ending in NNNN."
#   "Release day is getting closer! We'll process your preorder payment soon #NNN"
# Order number sits directly in the subject for every kind except the
# partial-cancel one, which only gives the last 4 digits -- not enough to
# key a match on, so that kind is flagged UNRECOGNIZED for the order-number
# field and must be resolved from the body's full number instead.
_TARGET_NUM = r"#\s?:?(\d{9,20})"
_TARGET_CONFIRM = re.compile(r"thanks for shopping with us.*here'?s your order " + _TARGET_NUM, re.I)
_TARGET_SHIPPED = re.compile(r"items from order " + _TARGET_NUM + r" are about to ship", re.I)
_TARGET_ARRIVES_SOON = re.compile(r"your order arrives (today|tomorrow)! order " + _TARGET_NUM, re.I)
_TARGET_ARRIVED = re.compile(r"items have arrived from order " + _TARGET_NUM, re.I)
_TARGET_CANCEL_FULL = re.compile(r"sorry, we had to cancel order " + _TARGET_NUM, re.I)
_TARGET_CANCEL_PARTIAL = re.compile(r"canceled items? from your order ending in (\d{3,4})", re.I)
_TARGET_PREORDER = re.compile(r"process your preorder payment soon " + _TARGET_NUM, re.I)

# --- Walmart -----------------------------------------------------------------
# Real subjects observed (threads 19fb16c3b8b9a43d, 19fcdf028a3903d7,
# 19fd30f3416361d0, 199c94785f7cf1c3):
#   "Thanks for your delivery order, Eugene"          (confirmation)
#   "Shipped: Pokemon Trading Card G..."               (truncated product name)
#   "Arrived: Your Pokemon Trading Card G..."
#   "Canceled: delivery from order #200013725750475"
#   "Eugene, thanks for your preorder"
# Walmart's confirmation subject carries NO order number (it's "Thanks for
# your delivery order, Eugene" -- a fixed greeting) or product name only,
# truncated with "...". The number is body-only for confirmations; only
# the cancellation template puts it in the subject.
_WALMART_CONFIRM = re.compile(r"thanks for your (delivery order|preorder)", re.I)
_WALMART_SHIPPED = re.compile(r"^shipped:", re.I)
_WALMART_ARRIVED = re.compile(r"^arrived:", re.I)
_WALMART_CANCELLED = re.compile(r"^canceled: delivery from order #(\S+)", re.I)


def classify(subject: str) -> Classification:
    """
    Pure function: subject line in, best-guess classification out.
    Never raises -- an unrecognized subject returns UNRECOGNIZED so the
    caller can log it and move on rather than crash a whole sync pass on
    one marketing email the retailer never templated for us.
    """
    s = (subject or "").strip()

    if _PC_CONFIRM.search(s):
        return Classification(Retailer.POKEMON_CENTER, EmailKind.CONFIRMATION, None)
    if _PC_SHIPPED.search(s):
        return Classification(Retailer.POKEMON_CENTER, EmailKind.SHIPPED, None)
    if _PC_CANCELLED.search(s):
        return Classification(Retailer.POKEMON_CENTER, EmailKind.CANCELLED_FULL, None)

    if m := _TARGET_CONFIRM.search(s):
        return Classification(Retailer.TARGET, EmailKind.CONFIRMATION, m.group(1))
    if m := _TARGET_SHIPPED.search(s):
        return Classification(Retailer.TARGET, EmailKind.SHIPPED, m.group(1))
    if m := _TARGET_ARRIVES_SOON.search(s):
        return Classification(Retailer.TARGET, EmailKind.SHIPPED, m.group(2))
    if m := _TARGET_ARRIVED.search(s):
        return Classification(Retailer.TARGET, EmailKind.ARRIVED, m.group(1))
    if m := _TARGET_CANCEL_FULL.search(s):
        return Classification(Retailer.TARGET, EmailKind.CANCELLED_FULL, m.group(1))
    if _TARGET_CANCEL_PARTIAL.search(s):
        # Order number not resolvable from the subject -- see module note.
        return Classification(Retailer.TARGET, EmailKind.CANCELLED_PARTIAL, None)
    if m := _TARGET_PREORDER.search(s):
        return Classification(Retailer.TARGET, EmailKind.PAYMENT_PENDING, m.group(1))

    if m := _WALMART_CANCELLED.search(s):
        return Classification(Retailer.WALMART, EmailKind.CANCELLED_FULL, m.group(1))
    if _WALMART_CONFIRM.search(s):
        return Classification(Retailer.WALMART, EmailKind.CONFIRMATION, None)
    if _WALMART_SHIPPED.search(s):
        return Classification(Retailer.WALMART, EmailKind.SHIPPED, None)
    if _WALMART_ARRIVED.search(s):
        return Classification(Retailer.WALMART, EmailKind.ARRIVED, None)

    return Classification(None, EmailKind.UNRECOGNIZED, None)
