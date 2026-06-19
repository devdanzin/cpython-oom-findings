"""OOM-0022 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: pdb.runcall() under the set_nomemory sweep. Deterministic (re-verified).
"""
import faulthandler, pdb
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(1000):
    set_nomemory(start)
    try:
        pdb.runcall()
    except BaseException:
        pass
print("done, no crash")
