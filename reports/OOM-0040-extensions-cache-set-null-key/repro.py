"""OOM-0040 mechanism reproducer (minimization PARTIAL).

SEGV: under a bounded OOM window, the extensions-cache key allocation fails (NULL) but the
later cache-value allocation succeeds, so `_extensions_cache_set` passes a NULL key to
`_Py_hashtable_set` -> `hashtable_hash_str` does `strlen(NULL)` -> SEGV (Python/import.c:1312).

This loop reaches that path by importing not-yet-cached C extensions under a windowed
`set_nomemory`, but a generic "import C extensions under OOM" sweep also trips OTHER
first-import OOM bugs (GC `validate_gc_objects` negative-refcount; the `co->_co_unique_id`
assert) that can fire first -- so this is a *mechanism demo*, not a clean isolated trigger.
The reliable reproducer is the preserved `vehicle_source.py` (target module `pdb`). The
defect itself is unconditional given a NULL key (see report.md "Root cause").

Needs a Py_DEBUG-or-not build (it is a real NULL deref, crashes release too) and
`_testcapi.set_nomemory`. Run under the free-threaded build with PYTHON_GIL=0.
"""
import faulthandler; faulthandler.enable()
import sys, importlib, gc
gc.disable()  # suppress one competing first-import OOM bug (GC validate_gc_objects)
from _testcapi import set_nomemory

DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)

CANDS = ["array", "_csv", "_lsprof", "mmap", "_random", "cmath", "unicodedata",
         "_struct", "select", "_socket", "binascii", "_pickle", "_zoneinfo", "_bz2", "_lzma"]

for start in range(6000):
    name = CANDS[start % len(CANDS)]
    sys.modules.pop(name, None)       # force a first-time (uncached) import -> _extensions_cache_set
    set_nomemory(start, start + 6)    # bounded window: key alloc fails, later allocs resume
    try:
        try:
            importlib.import_module(name)
        finally:
            set_nomemory(DISABLE, 0)
    except BaseException:
        pass
print("survived (no crash)")
