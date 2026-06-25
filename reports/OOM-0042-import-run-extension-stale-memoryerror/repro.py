"""OOM-0042 reproducer pointer (vehicle-confirmed; minimization partial).

The reliable reproducer is the preserved fuzzer vehicle `vehicle_source.py` (target `code`):
under fusil's --oom-seq windowed OOM it first-imports the single-phase C extension `readline`,
an allocation inside readline's init fails leaving a MemoryError pending, the init still
reports success, and `import_run_extension` aborts at its post-init invariant
`assert(!PyErr_Occurred())` (Python/import.c:2301). Reproduces 6/6 on debug-ft-nojit-asan
@1b9fe5c. gdb confirms: pending exception == MemoryError, init function == PyInit_readline.

The bare minimal below does NOT reproduce: a single-process `import readline` under a windowed
set_nomemory sweep cannot land the failure inside readline's init (a C extension runs PyInit
only once per process, so the sweep can't re-arm it; and the failing allocation must fall
inside the init, which the vehicle's broader allocation profile achieves but a bare import does
not -- the same first-import-under-OOM isolation difficulty as OOM-0040). Kept to document what
was ruled out.
"""
import sys
import faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

assert "readline" not in sys.modules
set_nomemory(40, 48)          # windowed failure (window 8, as the vehicle uses)
try:
    import readline           # noqa: F401
except BaseException:
    pass
finally:
    try:
        remove_mem_hooks()
    except Exception:
        pass
print("survived (no crash) -- use vehicle_source.py")
