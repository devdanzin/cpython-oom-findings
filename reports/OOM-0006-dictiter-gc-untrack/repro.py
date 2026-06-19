"""OOM-0006 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: _strptime._strptime("", "") under the set_nomemory sweep. Deterministic (re-verified).
"""
import faulthandler, _strptime
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(60):
    set_nomemory(start)
    try:
        _strptime._strptime("", "")
    except BaseException:
        pass
print("done, no crash")
