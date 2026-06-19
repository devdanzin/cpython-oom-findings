"""OOM-0011 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: optparse.ngettext(0.0, 0, "") (the import asyncio is load-bearing — it shifts the allocation window so a LOAD_ATTR specialization fails under OOM) under the set_nomemory sweep. Deterministic (re-verified).
"""
import faulthandler, asyncio, optparse   # the asyncio import is load-bearing (shrinkray kept it)
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(120):
    set_nomemory(start)
    try:
        optparse.ngettext(0.0, 0, "")
    except BaseException:
        pass
print("done, no crash")
