"""OOM-0007 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: importlib.metadata.metadata("f") under the set_nomemory sweep. Deterministic (re-verified).
"""
import faulthandler, importlib.metadata
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(40):
    set_nomemory(start)
    try:
        importlib.metadata.metadata("f")
    except BaseException:
        pass
print("done, no crash")
