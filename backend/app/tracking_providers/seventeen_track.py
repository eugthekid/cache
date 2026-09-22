"""
seventeen_track.py
-------------------
TrackingProvider implementation for 17TRACK (https://api.17track.net),
chosen 2026-09-19 -- see app/tracking.py's module docstring for why.

TWO-STEP MODEL, specific to this provider: a tracking number has to be
REGISTERED once before /gettrackinfo returns anything for it, and that
registration is what consumes the free-tier quota (100/month); querying
an already-registered number afterward is free and unlimited. Rather
than store a 17TRACK-specific "is this registered" flag on Order (which
would leak this provider's own model into the shared schema -- see this
package's own __init__.py), fetch() just tries the query FIRST and only
registers on demand, the one time a number turns out to be unseen. That
keeps the two-step dance entirely inside this file: to every caller,
fetch() is one call, same as any other provider would offer.

STATUS MAPPING: 17TRACK's own 9-value status taxonomy (NotFound,
InfoReceived, InTransit, Expired, AvailableForPickup, OutForDelivery,
DeliveryFailure, Delivered, Exception) never reaches the rest of the app
-- _STATUS_MAP below is the one place it gets translated to Order's own
5-value shipping_status enum ('not_shipped' | 'label_created' |
'in_transit' | 'delivered' | 'exception'). OutForDelivery and
AvailableForPickup don't map cleanly onto that enum (both are still
"in transit" in Cache's terms, but both are moments worth telling the
user about) -- see TrackingUpdate.alert for how that's handled without
inventing new enum values.
"""

from typing import Any, Optional

import httpx

from app.tracking import TrackingUpdate

_BASE_URL = "https://api.17track.net/track/v2.4"

# 17TRACK's own status string -> Order.shipping_status. None means "no
# real signal yet, don't touch the existing value" -- NotFound covers
# both "not registered yet" (handled below, before this map is even
# consulted) and a genuinely blank carrier scan history.
_STATUS_MAP: dict[str, Optional[str]] = {
    "NotFound": None,
    "InfoReceived": "label_created",
    "InTransit": "in_transit",
    "Expired": "exception",  # "in transit longer than expected" -- worth a look
    "AvailableForPickup": "in_transit",  # not yet in hand; alert=True carries the urgency
    "OutForDelivery": "in_transit",  # ditto -- arriving today, not yet delivered
    "DeliveryFailure": "exception",
    "Delivered": "delivered",
    "Exception": "exception",
}

# Statuses worth an OS notification even though they don't move
# shipping_status into the {'delivered','exception'} set
# sync_tracking_fields() already edge-triggers on -- see TrackingUpdate.alert.
_ALERT_STATUSES = {"OutForDelivery", "AvailableForPickup", "DeliveryFailure", "Exception"}

_STATUS_DETAIL: dict[str, str] = {
    "InfoReceived": "Label created",
    "InTransit": "In transit",
    "Expired": "In transit longer than expected",
    "AvailableForPickup": "Available for pickup",
    "OutForDelivery": "Out for delivery",
    "DeliveryFailure": "Delivery attempted, unsuccessful",
    "Delivered": "Delivered",
    "Exception": "Exception -- may be returned or held",
}


class SeventeenTrackProvider:
    def __init__(self, api_key: str, client: Optional[httpx.Client] = None) -> None:
        self._api_key = api_key
        # Injectable for tests -- see tests/test_seventeen_track.py, which
        # passes a fake client that never touches the network.
        self._client = client or httpx.Client(
            base_url=_BASE_URL,
            headers={"17token": api_key, "Content-Type": "application/json"},
            timeout=10.0,
        )

    def fetch(self, tracking_number: str, carrier: Optional[str] = None) -> TrackingUpdate:
        info = self._get_track_info(tracking_number)
        if info is None:
            # Unseen by 17TRACK -- register once, then query again. A
            # registration failure (bad number, carrier truly
            # undetectable) is a real "nothing to report" case, not an
            # error the poller should crash a whole cycle over.
            if not self._register(tracking_number):
                return TrackingUpdate()
            info = self._get_track_info(tracking_number)
            if info is None:
                return TrackingUpdate()

        latest_status = (info.get("latest_status") or {}).get("status")
        latest_event = info.get("latest_event") or {}
        time_metrics = info.get("time_metrics") or {}

        shipping_status = _STATUS_MAP.get(latest_status)
        detail = latest_event.get("description") or _STATUS_DETAIL.get(latest_status)
        estimated_delivery = time_metrics.get("estimated_delivery_date")
        # Defensive: some responses give a {from, to} range instead of a
        # single date -- take the "to" edge (the later, more useful bound
        # for "expect it by") rather than crash on an unexpected shape.
        if isinstance(estimated_delivery, dict):
            estimated_delivery = estimated_delivery.get("to") or estimated_delivery.get("from")

        return TrackingUpdate(
            shipping_status=shipping_status,
            estimated_delivery=estimated_delivery,
            detail=detail,
            alert=latest_status in _ALERT_STATUSES,
        )

    def _get_track_info(self, tracking_number: str) -> Optional[dict[str, Any]]:
        response = self._client.post("/gettrackinfo", json=[{"number": tracking_number}])
        response.raise_for_status()
        body = response.json()
        accepted = ((body.get("data") or {}).get("accepted")) or []
        for row in accepted:
            if row.get("number") == tracking_number:
                track_info = row.get("track_info")
                if track_info and track_info.get("latest_status"):
                    return track_info
        return None

    def _register(self, tracking_number: str) -> bool:
        response = self._client.post("/register", json=[{"number": tracking_number}])
        response.raise_for_status()
        body = response.json()
        accepted = ((body.get("data") or {}).get("accepted")) or []
        return any(row.get("number") == tracking_number for row in accepted)
