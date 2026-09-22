"""
tracking_providers/
--------------------
Concrete implementations of app/tracking.py's TrackingProvider protocol.
Each provider's own vocabulary, quota model and API quirks stay inside
its own file here -- the rest of the app (tracking_poller.py, the Order
model, the frontend) only ever sees the generic TrackingUpdate shape
that protocol defines. Swapping providers later means adding a new file
here and changing one line in tracking.resolve_provider(), nothing else.
"""
