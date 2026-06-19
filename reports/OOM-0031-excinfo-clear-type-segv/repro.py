"""OOM-0031: _interpreters.exec under OOM frees an invalid cross-interpreter excinfo.

_excinfo_clear_type (Python/crossinterp.c:1319) dereferences an uninitialized/dangling
`info` (member of a _PyXI_excinfo) while cleaning up after an _interpreters.exec whose
exception-capture allocation failed under OOM -> SIGSEGV on all builds.

Minimization PARTIAL/vehicle-confirmed: this reduction exercises the exec path but did
not hit the exact OOM window in budget. Reliable reproducer is `vehicle_source.py`
(fusil fuzzing _interpreters.exec under the set_nomemory sweep); it SIGSEGVs
deterministically on all four local builds.
"""
import _interpreters
from _testcapi import set_nomemory, remove_mem_hooks

iid = _interpreters.create()
for start in range(1, 3000):
    set_nomemory(start, 0)
    try:
        try:
            _interpreters.exec(iid, "raise ValueError('x')")
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
