"""OOM-0022 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: pdb.runcall() under the set_nomemory sweep. Deterministic on the ft_debug_asan
build (re-verified 10/10). NOTE: this minimal repro is ft_debug_asan-specific — the report's
build matrix (which records jit=fatal too) is verified against the full vehicle_source.py;
this minimal repro does not exercise the readline single-phase-extension reload path the
vehicle hits, so it only fatals on ft_debug_asan.
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
