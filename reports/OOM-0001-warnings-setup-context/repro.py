"""
Minimal reproducer: NULL-deref / segfault in CPython's warnings machinery under OOM.

Affected:   CPython 3.16.0a0 (seen on a free-threaded debug+ASan build; the defect
            is allocation-failure handling and is not build-specific).
Crash:      SIGSEGV in Py_DECREF(filename) with filename == NULL.
Requires:   a build exposing _testcapi.set_nomemory (debug/test builds).

Run:
    python repro_warnings_oom_minimal.py
    # exits via SIGSEGV (ASan: "SEGV on unknown address"; faulthandler prints
    #  "File ... in warn" / the warnings.warn() call site)

Authoritative backtrace (gdb, debug build):
    #0 _Py_atomic_load_uint32_relaxed   Include/cpython/pyatomic_gcc.h:367
    #1 Py_DECREF                        Include/refcount.h:345
    #2 do_warn                          Python/_warnings.c:1139   <- Py_DECREF(filename), filename==NULL
    #3 warnings_warn_impl               Python/_warnings.c:1184
    #4 warnings_warn                    Python/clinic/_warnings.c.h:161
    ...

Root cause (Python/_warnings.c, setup_context()):
    The `f == NULL` branch assigns
        *filename = PyUnicode_FromString("<sys>");
    with NO NULL check. Under memory pressure two allocations fail in sequence:
      (a) PyThreadState_GetFrame() returns NULL (its frame-object allocation
          fails), so the `f == NULL` branch is taken; then
      (b) PyUnicode_FromString("<sys>") itself returns NULL, leaving
          *filename == NULL.
    The NULL *filename is then passed to Py_DECREF:
      - if setup_context() returns success (registry/__name__ already present in
        globals, so no further allocation is needed), do_warn() runs its cleanup
        `Py_DECREF(filename)` at _warnings.c:1139  -> NULL deref;  OR
      - if setup_context() instead reaches its `handle_error:` label, that path
        runs `Py_DECREF(*filename)` (note: not Py_XDECREF) at _warnings.c:1087
        -> NULL deref.
    Both observed faulting sites (1139 and 1087) are the same NULL *filename.

Likely fix: NULL-check PyUnicode_FromString("<sys>") (goto handle_error on NULL),
and use Py_XDECREF(*filename) in the handle_error path.

This single defect accounts for 8 of the 13 "segfault" crashers in this run
(_pyio, asyncio_streams, asyncio_threads x2, genericpath, urllib_parse,
importlib._bootstrap_external via do_warn:1139; multiprocessing.resource_tracker
via setup_context:1087). The various stdlib modules are only vehicles that emit a
warning under OOM.
"""
import _testcapi
import warnings
import faulthandler

faulthandler.enable()
warnings.simplefilter("always")   # make sure warn() runs its full path every time

_testcapi.set_nomemory(0, 0)      # fail every allocation from this point on
warnings.warn("boom")             # -> do_warn()/setup_context() Py_DECREF(NULL) -> SIGSEGV

# Not reached. If the interpreter is ever fixed, remove the hook here:
_testcapi.remove_mem_hooks()
