"""OOM-0031 minimal reproducer (stdlib only) — reduced from the fuzzer vehicle with shrinkray.

`_interpreters.capture_exception(exc)` builds a cross-interpreter `_PyXI_excinfo` from the
exception. Under allocation failure the capture fails partway, and the cleanup path
`_PyXI_FreeExcInfo -> _PyXI_excinfo_clear -> _excinfo_clear_type` runs on an uninitialized /
dangling `info`, dereferencing it at Python/crossinterp.c:1319 -> SIGSEGV (all builds).

shrinkray found `capture_exception` reaches the bug directly — a simpler trigger than the
original `_interpreters.exec` path. Deterministic (re-verified 40x).
"""
import faulthandler
import _interpreters
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(0, 40):
    try:
        set_nomemory(start, 0)
        try:
            _interpreters.capture_exception(Exception())
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
    except BaseException:
        pass
    finally:
        try:
            remove_mem_hooks()
        except Exception:
            pass
print("done, no crash")
