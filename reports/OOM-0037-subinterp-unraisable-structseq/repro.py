"""
OOM-0037 — NULL-pointer segfault in the unraisable-exception reporter during
sub-interpreter finalization under OOM.

A sub-interpreter created by an `InterpreterPoolExecutor` worker fails to
initialize under allocation failure. `new_interpreter()` tears the half-built
interpreter down via `Py_EndInterpreter()`, whose `wait_for_thread_shutdown()`
tries to report the pending `MemoryError` as an unraisable exception. That goes
through `PyStructSequence_New(&UnraisableHookArgsType)`, but the per-interpreter
`UnraisableHookArgs` structseq type was never initialized in this sub-interpreter
(its `tp_dict` is NULL), so `get_type_attr_as_size()` calls
`PyDict_GetItemWithError(NULL, ...)` → `Py_TYPE(NULL)` → SIGSEGV.

Reproduces on every build (release too): NULL deref, not a debug-only assert.

The **windowed** failure is essential: `set_nomemory(start, k)` with k>0 fails k
allocations and then *resumes*, letting the worker get far enough to attempt
sub-interpreter creation and fail mid-init. Fail-forever (`set_nomemory(start, 0)`)
only starves/hangs the executor and never reaches the crash.

Requires a build exposing `_testcapi.set_nomemory` (debug/test builds).

Run:
    ./python repro.py        # SIGSEGV mid-loop (rc 139, or rc 1 under ASan)
"""
import faulthandler
faulthandler.enable()

from concurrent.futures import InterpreterPoolExecutor
from _testcapi import set_nomemory, remove_mem_hooks

ex = InterpreterPoolExecutor()
for start in range(150):
    set_nomemory(start, 5)        # windowed: fail allocs [start, start+5), then resume
    try:
        ex.submit(int)           # a worker spins up a sub-interpreter under OOM
    except BaseException:         # the task itself never runs — the crash is during create
        pass
remove_mem_hooks()
