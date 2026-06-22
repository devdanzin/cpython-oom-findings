"""
OOM-0005 -- USE-AFTER-FREE face (in addition to the negative-refcount abort in repro.py).

Same defect: `_PyFrame_ClearLocals` (Python/frame.c:101) over-decrefs a frame local via
`PyStackRef_XCLOSE` during frame unwind under OOM. When that local is *also* referenced
elsewhere (here, held in a dict), the over-decref frees it while it is still live -> a real
use-after-free, not just a refcount-imbalance assert.

Reduced (shrinkray) from a `pkgutil` fuzzing vehicle. The freed object is the `str` argument
threaded through `pkgutil.get_importer(path) -> os.fsdecode(path) -> os.fspath(path)`:

  - debug-gil-nojit-asan: ASan reports a clean `heap-use-after-free`
        READ  : Py_INCREF <- _Py_dict_lookup_threadsafe (dictobject.c:1729)   [a later dict use]
        FREED : PyStackRef_XCLOSE@stackref.h:726 <- _PyFrame_ClearLocals@frame.c:101 (exit_unwind)
        ALLOC : PyUnicode_New <- long_to_decimal_string <- PyObject_Str   (i.e. str(0))
    (see backtrace_uaf.txt)
  - debug-ft-nojit-asan: the same freed local is instead used by `PyOS_FSPath`
        (posixmodule.c:17168) -> `PyType_HasFeature` reads `Py_TYPE(path)->tp_flags` on the
        freed object (ob_type == 0xdd debug-freed fill) -> SIGSEGV.

So the `PyOS_FSPath`/`os.fspath` segv is NOT a separate bug -- it is one downstream *use* of
the local OOM-0005 frees. Which downstream use crashes (dict-lookup INCREF vs os.fspath type
read) depends on build/timing.

Requires a build exposing `_testcapi.set_nomemory`. Reproduces deterministically (>=5/5) on the
free-threaded and GIL debug+ASan builds; the structure matters -- the crashing call must run
through a nested Python frame (the `sweep(thunk)` wrapper), matching how the fuzzer's
oom_run(thunk) invokes it; a flat module-level loop does not reproduce.

Run:  ./python repro_uaf.py     # ft-debug-asan: SIGSEGV in PyOS_FSPath ; gil-debug-asan: ASan heap-use-after-free
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
