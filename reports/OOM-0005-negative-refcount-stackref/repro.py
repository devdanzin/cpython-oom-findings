"""OOM-0005 reproducer (stdlib only) -- eval-loop stackref over-decref under OOM.

`_PyFrame_ClearLocals` (Python/frame.c:101) closes a `_PyStackRef` still on a frame's value
stack via `PyStackRef_XCLOSE` during the exception-unwind (`exit_unwind`) path. Under OOM an
error path left that stackref dangling, so the close drives the referenced object's refcount
below zero. On a debug build this aborts (`_Py_NegativeRefcount`); when the object is ALSO
referenced elsewhere, the close frees a still-live object -> a real use-after-free.

This reproducer demonstrates the use-after-free directly. The freed object is the `str`
argument threaded through `pkgutil.get_importer(s) -> os.fsdecode(s) -> os.fspath(s)`; the same
string is also kept alive in a dict, so the over-decref frees it while still referenced:
  - debug-gil-nojit-asan: ASan reports a clean `heap-use-after-free` whose freed-by stack is
    exactly this site (`PyStackRef_XCLOSE`@pycore_stackref.h:726 <- `_PyFrame_ClearLocals`@frame.c:101,
    exit_unwind); the later read is a `Py_INCREF` via a dict lookup; the alloc is the victim str.
  - debug-ft-nojit-asan: the same freed local is instead used by `PyOS_FSPath`
    (posixmodule.c:17168) -> `PyType_HasFeature` reads `Py_TYPE(path)->tp_flags` on freed memory
    (ob_type == 0xdd) -> SIGSEGV.
So the `PyOS_FSPath`/`os.fspath` segv is not a separate bug -- it is one downstream USE of the
local that `_PyFrame_ClearLocals` over-decrefs.

Deterministic (>=5/5) on the free-threaded and GIL debug+ASan builds; requires a build exposing
`_testcapi.set_nomemory`. The structure matters -- the crashing call must run through a nested
Python frame (the `sweep(thunk)` wrapper), matching how the fuzzer's `oom_run(thunk)` invokes it;
a flat module-level loop does not reproduce. See backtrace.txt.

rr note (2026-06-24): `rr` reverse-execution confirmed the over-decref here is NOT the
`_CALL_LIST_APPEND` list.append double-free (that is OOM-0036, python/cpython#151818). The str
argument is referenced by the holding dict + several call frames + the raised OSError's fields +
an args tuple, and the OOM-unwind dealloc cascade decrefs it one time too many. (An earlier
`xml.dom.minidom.parse(0)` reproducer for OOM-0005 was found by rr to actually be OOM-0036 and
was removed; it now lives in the OOM-0036 report as repro_xml_minidom.py.)

Run:  ./python repro.py     # ft-debug-asan: SIGSEGV in PyOS_FSPath ; gil-debug-asan: ASan heap-use-after-free
"""
import pkgutil
import faulthandler
faulthandler.enable()
from _testcapi import set_nomemory

d = {"s": str}
d["arg"] = d["s"](0)            # a heap str ("0"), also kept alive by this dict

def sweep(thunk):
    for start in range(60):
        set_nomemory(start)     # fail every allocation from #start onward
        try:
            thunk()
        except BaseException:
            pass

def call_get_importer():
    pkgutil.get_importer(d["arg"])   # -> os.fsdecode -> os.fspath; the arg is freed mid-unwind

sweep(call_get_importer)
