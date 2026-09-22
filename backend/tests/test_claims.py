"""
Exercises app/claims.py's resolve() directly against synthetic claims --
no DB, no fixtures, matching the module's own "deliberately DB-free and
pure" design.

THE BUG THIS FILE PROVES FIXED, FOUND LIVE against real Gmail data
(2026-09-18): resolve() used to break same-authority ties purely by
recency -- "the later claim wins." That is correct for every field except
status, where it silently reverted 'cancelled' back to 'success': a
retailer's cancellation and confirmation emails for the same order
routinely land seconds apart in one transactional burst, and the
confirmation's own Date header is frequently the LATER of the two by
nothing more than mail-queue jitter, not true business-event order.
Checked against 88 real email cancel-messages in the live database: 58
orders were resolving to 'success' despite a cancellation claim on file,
including "Pokemon TCG: 30th Celebration Pokemon Center Elite Trainer
Box." The fix makes 'cancelled' sticky within a rank: a same-or-weaker
authority claim can no longer move status off 'cancelled', no matter how
much later it arrived. A STRONGER authority (e.g. the user's own manual
edit) still can -- that escape hatch is exercised below too.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.claims import Claim, resolve

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


def t(hour, minute, second):
    return datetime(2026, 7, 15, hour, minute, second, tzinfo=timezone.utc)


# --- the live bug: same-source cancel then later same-source confirm -------
# This is the exact real-world shape: PokemonCenter's cancellation and
# confirmation for one order, 7 seconds apart, both from "email".
cancel_first = Claim(source="email", occurred_at=t(2, 45, 43), fields={"status": "cancelled"})
confirm_later = Claim(source="email", occurred_at=t(2, 45, 50), fields={"status": "success"})

result = resolve([cancel_first, confirm_later])
check("later same-source confirmation does not un-cancel", result["status"], "cancelled")

# Order-independence must still hold: same claims, reversed arrival.
result_reversed = resolve([confirm_later, cancel_first])
check("order-independent regardless of arrival order", result_reversed["status"], "cancelled")


# --- stronger authority can still override a cancellation ------------------
# A user's own correction (top of SOURCE_RANK) must still be able to move
# status off 'cancelled' -- cancellation is sticky against same-or-weaker
# authority, not immovable.
cancel = Claim(source="email", occurred_at=t(2, 45, 43), fields={"status": "cancelled"})
user_override = Claim(source="user", occurred_at=t(2, 0, 0), fields={"status": "success"})

result = resolve([cancel, user_override])
check("a stronger-authority claim can still move status off cancelled", result["status"], "success")


# --- a genuinely later cancellation must still win over an old success -----
# Guards against an overcorrection: making status sticky in general, not
# just sticky FOR cancelled, would break the ordinary "order shipped, then
# was cancelled after all" case.
success_first = Claim(source="email", occurred_at=t(1, 0, 0), fields={"status": "success"})
cancel_later = Claim(source="email", occurred_at=t(3, 0, 0), fields={"status": "cancelled"})

result = resolve([success_first, cancel_later])
check("a later cancellation still overrides an earlier success", result["status"], "cancelled")


# --- non-status fields are unaffected by the special case -------------------
# The sticky rule must be scoped to 'status' only -- every other field
# keeps ordinary same-source recency-wins behavior.
old_tracking = Claim(source="email", occurred_at=t(1, 0, 0), fields={"tracking_number": "OLD123"})
new_tracking = Claim(source="email", occurred_at=t(2, 0, 0), fields={"tracking_number": "NEW456"})

result = resolve([old_tracking, new_tracking])
check("non-status fields still resolve by plain recency", result["tracking_number"], "NEW456")


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
