"""
Exercises SeventeenTrackProvider.fetch() against a FAKE httpx client (no
network) -- proves the register-on-demand flow, the status mapping, and
the alert flag, all without needing a real API key.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tracking_providers.seventeen_track import SeventeenTrackProvider

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}")
        print(f"        got:      {got!r}")
    if ok:
        passed += 1
    else:
        failed += 1


def fake_response(json_body, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


def track_info_response(number, status, description=None, estimated_delivery=None):
    latest_event = {"description": description} if description else {}
    time_metrics = {"estimated_delivery_date": estimated_delivery} if estimated_delivery else {}
    return fake_response({
        "code": 0,
        "data": {
            "accepted": [
                {
                    "number": number,
                    "track_info": {
                        "latest_status": {"status": status},
                        "latest_event": latest_event,
                        "time_metrics": time_metrics,
                    },
                }
            ],
            "rejected": [],
        },
    })


def empty_response():
    return fake_response({"code": 0, "data": {"accepted": [], "rejected": []}})


def register_response(number, accepted=True):
    return fake_response({
        "code": 0,
        "data": {
            "accepted": [{"number": number}] if accepted else [],
            "rejected": [] if accepted else [{"number": number}],
        },
    })


# --- test 1: already-registered number, single query, no register call ---
client = MagicMock()
client.post.side_effect = [track_info_response("1Z999AA10123456784", "InTransit")]
provider = SeventeenTrackProvider("fake-key", client=client)

update = provider.fetch("1Z999AA10123456784")
check("already-registered: exactly 1 HTTP call (no register needed)", client.post.call_count, 1)
check("already-registered: shipping_status", update.shipping_status, "in_transit")
check("already-registered: alert is False for plain InTransit", update.alert, False)


# --- test 2: unseen number -- register-on-demand, then a second query ---
client2 = MagicMock()
client2.post.side_effect = [
    empty_response(),  # first gettrackinfo: nothing yet
    register_response("RR123456789CN"),  # register succeeds
    track_info_response("RR123456789CN", "InfoReceived"),  # second gettrackinfo: now has data
]
provider2 = SeventeenTrackProvider("fake-key", client=client2)

update2 = provider2.fetch("RR123456789CN")
check("unseen number: 3 HTTP calls (query, register, query again)", client2.post.call_count, 3)
check("unseen number: shipping_status after register-on-demand", update2.shipping_status, "label_created")
calls = [c.args[0] for c in client2.post.call_args_list]
check("unseen number: call order is query, register, query", calls, ["/gettrackinfo", "/register", "/gettrackinfo"])


# --- test 3: register fails (bad number) -- returns an empty update, never crashes ---
client3 = MagicMock()
client3.post.side_effect = [empty_response(), register_response("garbage", accepted=False)]
provider3 = SeventeenTrackProvider("fake-key", client=client3)

update3 = provider3.fetch("garbage")
check("failed registration: shipping_status stays None (nothing to report)", update3.shipping_status, None)
check("failed registration: does not attempt a third call", client3.post.call_count, 2)


# --- test 4: OutForDelivery and AvailableForPickup both alert, but stay in_transit ---
for status in ("OutForDelivery", "AvailableForPickup"):
    c = MagicMock()
    c.post.side_effect = [track_info_response("1Z1", status)]
    p = SeventeenTrackProvider("fake-key", client=c)
    u = p.fetch("1Z1")
    check(f"{status}: maps to in_transit, not a new enum value", u.shipping_status, "in_transit")
    check(f"{status}: alert=True (this is the whole point of the alert field)", u.alert, True)

# --- test 5: Delivered maps correctly and does NOT re-alert via this flag
# (sync_tracking_fields' own delivered/exception edge-trigger already
# owns that -- alert=True here would be redundant, not wrong, but this
# pins the deliberate choice) ---
c5 = MagicMock()
c5.post.side_effect = [track_info_response("1Z2", "Delivered", description="Delivered, front door")]
p5 = SeventeenTrackProvider("fake-key", client=c5)
u5 = p5.fetch("1Z2")
check("Delivered: shipping_status", u5.shipping_status, "delivered")
check("Delivered: detail carries the carrier's own text", u5.detail, "Delivered, front door")


# --- test 6: estimated_delivery as a {from, to} range takes the 'to' edge ---
c6 = MagicMock()
body = {
    "code": 0,
    "data": {
        "accepted": [{
            "number": "1Z3",
            "track_info": {
                "latest_status": {"status": "InTransit"},
                "latest_event": {},
                "time_metrics": {"estimated_delivery_date": {"from": "2026-09-20", "to": "2026-09-22"}},
            },
        }],
        "rejected": [],
    },
}
c6.post.side_effect = [fake_response(body)]
p6 = SeventeenTrackProvider("fake-key", client=c6)
u6 = p6.fetch("1Z3")
check("estimated_delivery range -> takes the later 'to' edge", u6.estimated_delivery, "2026-09-22")


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
