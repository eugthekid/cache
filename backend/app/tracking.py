"""
tracking.py
-----------
Carrier identification and tracking-URL construction, plus the seam a live
carrier API plugs into later.

WHY THIS IS SPLIT FROM THE API CALL: everything here works offline, with no
account, no key, and no network -- a tracking number's FORMAT identifies its
carrier on its own. That covers the two things worth having immediately (know
who's carrying it, click straight through to the carrier's own page) without
blocking on a provider decision. `TrackingProvider` below is the interface a
real integration implements to fill in live status and an ETA; when no
provider is configured, `resolve_provider()` returns None and callers simply
skip the live half.

LIVE PROVIDER, as of 2026-09-19: 17TRACK (app/tracking_providers/
seventeen_track.py), chosen for a genuinely free tier at this app's scale
(100 tracking-number registrations/month, no card, unlimited re-checks
after registering) over AfterShip (API access needs its $70/mo paid tier)
and EasyPost/Shippo (built for generating shipping labels; tracking-only
has no real free tier). Deliberately swappable: this module and
TrackingUpdate only ever expose generic fields, so a future switch is a
new file in tracking_providers/ and one line here, not a schema change.

MATCHING DISCIPLINE, same as catalog.py and products.py: an AMBIGUOUS number
returns None rather than a guess. Several carriers share the plain-N-digits
shape, and labelling a FedEx package "USPS" would send the user to a page that
says the number doesn't exist -- strictly worse than showing nothing. Only
patterns that are actually distinctive resolve to a carrier.
"""

import re
from typing import Optional, Protocol

# 'ups' | 'fedex' | 'usps' | 'dhl'
CARRIER_LABELS = {
    "ups": "UPS",
    "fedex": "FedEx",
    "usps": "USPS",
    "dhl": "DHL",
}

# Ordered most-distinctive first: the first match wins, so anything that
# could collide with a later, vaguer pattern has to be listed above it.
_CARRIER_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 1Z + 16 alphanumerics. Unique to UPS and unmistakable.
    ("ups", re.compile(r"^1Z[0-9A-Z]{16}$", re.IGNORECASE)),
    # UPS Mail Innovations / "T" numbers.
    ("ups", re.compile(r"^T\d{10}$", re.IGNORECASE)),
    # USPS international: 2 letters + 9 digits + "US" (S10 standard).
    ("usps", re.compile(r"^[A-Z]{2}\d{9}US$", re.IGNORECASE)),
    # USPS domestic IMpb: 22 digits opening with a 91-95 service code, or
    # the 420+ZIP prefixed form. The leading code is what separates these
    # from FedEx's own 20-22 digit numbers.
    ("usps", re.compile(r"^(?:420\d{5,9})?9[1-5]\d{20}$")),
    ("usps", re.compile(r"^(?:420\d{5,9})?9[1-5]\d{18}$")),
    # DHL Express: 10 digits, optionally with a JJD/JD prefix.
    ("dhl", re.compile(r"^JJD\d{16,20}$", re.IGNORECASE)),
    ("dhl", re.compile(r"^JD\d{18}$", re.IGNORECASE)),
    # FedEx SmartPost, and FedEx Ground's 96-prefixed 22-digit form.
    ("fedex", re.compile(r"^96\d{20}$")),
    # FedEx Express: 12 digits. Distinctive enough to keep -- no other
    # major carrier issues a bare 12-digit number.
    ("fedex", re.compile(r"^\d{12}$")),
    # FedEx Ground: 15 digits.
    ("fedex", re.compile(r"^\d{15}$")),
]

_TRACKING_URLS = {
    "ups": "https://www.ups.com/track?tracknum={number}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={number}",
    "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={number}",
    "dhl": "https://www.dhl.com/en/express/tracking.html?AWB={number}",
}


def normalize_tracking_number(raw: Optional[str]) -> Optional[str]:
    """Strips the spaces and dashes people paste in from a carrier page or
    a confirmation email. Returns None for anything left empty."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s-]", "", raw).strip()
    return cleaned or None


def detect_carrier(tracking_number: Optional[str]) -> Optional[str]:
    """
    The carrier a tracking number's format identifies, or None when nothing
    matches distinctively. None is a real answer here, not a failure -- see
    this module's docstring on why a guess is worse than nothing.
    """
    number = normalize_tracking_number(tracking_number)
    if not number:
        return None
    for carrier, pattern in _CARRIER_PATTERNS:
        if pattern.match(number):
            return carrier
    return None


def tracking_url(tracking_number: Optional[str], carrier: Optional[str] = None) -> Optional[str]:
    """A direct link to the carrier's own tracking page, or None when the
    carrier is unknown (there's no generic page worth linking to)."""
    number = normalize_tracking_number(tracking_number)
    if not number:
        return None
    resolved = carrier or detect_carrier(number)
    template = _TRACKING_URLS.get(resolved or "")
    return template.format(number=number) if template else None


class TrackingProvider(Protocol):
    """
    What a live carrier integration has to implement.

    Deliberately narrow: one call, one shipment, returning only the fields
    Order actually stores. Keeping it this small is what lets the provider
    be swapped (or stay absent) without anything else in the app changing.
    """

    def fetch(self, tracking_number: str, carrier: Optional[str]) -> "TrackingUpdate":
        ...


class TrackingUpdate:
    """
    One provider's answer about one shipment.

    `alert` is deliberately its own field, separate from `shipping_status`:
    a provider-specific moment worth notifying about -- out for delivery,
    available for pickup at a locker -- doesn't always map cleanly onto
    Order's own coarse 5-value shipping_status enum, and inventing a new
    enum value per provider-specific nuance would leak that provider's
    vocabulary into the schema. `alert=True` says "tell the user now",
    `detail` says why, in the provider's own words; the poller is what
    turns that into an actual notification, edge-triggered on `detail`
    actually changing so the same status doesn't re-alert every cycle.
    """

    def __init__(
        self,
        shipping_status: Optional[str] = None,
        estimated_delivery: Optional[str] = None,
        carrier: Optional[str] = None,
        detail: Optional[str] = None,
        alert: bool = False,
    ) -> None:
        self.shipping_status = shipping_status
        self.estimated_delivery = estimated_delivery
        self.carrier = carrier
        self.detail = detail
        self.alert = alert


def resolve_provider(api_key: Optional[str] = None) -> Optional[TrackingProvider]:
    """
    The configured live-tracking provider, or None when there isn't one.

    Takes the credential as a plain argument rather than reading a config
    file itself -- same separation as email_poller.py: routers/
    tracking_account.py and tracking_poller.py own reading
    tracking.env, this function just builds the provider object. None
    when api_key is falsy, so every caller can pass through whatever it
    read without an extra "is this configured" branch of its own.
    """
    if not api_key:
        return None
    from app.tracking_providers.seventeen_track import SeventeenTrackProvider

    return SeventeenTrackProvider(api_key)
