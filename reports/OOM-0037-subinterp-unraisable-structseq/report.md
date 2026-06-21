# Segfault: NULL `UnraisableHookArgs` type-dict deref reporting an unraisable during sub-interpreter finalization under OOM (`structseq.c:30` / `errors.c:1422`)

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When a sub-interpreter fails to initialize under allocation failure, CPython tears the
half-built interpreter down (`new_interpreter` → `Py_EndInterpreter`). During that teardown
`wait_for_thread_shutdown()` reports the pending `MemoryError` as an *unraisable* exception,
which calls `PyStructSequence_New(&UnraisableHookArgsType)`. But that per-interpreter structseq
type was never initialized in the failed sub-interpreter (`tp_dict == NULL`), so
`get_type_attr_as_size()` calls `PyDict_GetItemWithError(NULL, ...)` → `Py_TYPE(NULL)` → SIGSEGV.
Reproduces on **all** builds (release included) — a real NULL-pointer dereference, not a
debug-only assertion.

## Reproducer

```python
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
```

Deterministic (≈100%, re-verified 20/20) on the free-threaded debug+ASan build, and crashes
the GIL, JIT, and **release** builds too. The **windowed** failure is required: a worker must
get far enough to attempt sub-interpreter creation and then fail mid-init; fail-forever
(`set_nomemory(start, 0)`) only starves the executor and hangs. Reproduces with and without
`PYTHON_GIL=1`. (Reduced from a `concurrent.futures.interpreter` fuzzing vehicle, preserved as
`vehicle_source.py`.)

## Backtrace

SEGV on `0x18` = `Py_TYPE(NULL)` (worker thread; debug-ft-nojit-asan, commit `1b9fe5c`):

```
#0 _Py_TYPE_impl            Include/object.h:234        Py_TYPE(op), op == NULL
#1 PyDict_GetItemWithError  Objects/dictobject.c:2613   op (the dict) == NULL
#2 get_type_attr_as_size    Objects/structseq.c:30      PyDict_GetItemWithError(_PyType_GetDict(tp), name)
#3 PyStructSequence_New     Objects/structseq.c:68
#4 make_unraisable_hook_args Python/errors.c:1422       PyStructSequence_New(&UnraisableHookArgsType)
#5 format_unraisable_v      Python/errors.c:1706
#6 PyErr_FormatUnraisable   Python/errors.c:1777
#7 wait_for_thread_shutdown Python/pylifecycle.c:3856   reports the pending exception
#9 Py_EndInterpreter        Python/pylifecycle.c:2811   tearing down the half-built subinterp
#10 new_interpreter         Python/pylifecycle.c:2755   OOM failure path
#12 _PyXI_NewInterpreter    Python/crossinterp.c:3269
#13 _interpreters_create_impl Modules/_interpretersmodule.c:878   (InterpreterPoolExecutor worker)
```

gdb on the debug build confirms it is a clean NULL (not a freed/dangling pointer):

```
(get_type_attr_as_size)  tp          = <UnraisableHookArgsType>     tp->tp_name = "UnraisableHookArgs"
                         tp->tp_dict  = 0x0          <- type never initialized in this subinterp
(PyDict_GetItemWithError) op         = 0x0          <- the NULL dict that is then dereferenced
```

## Root cause

`make_unraisable_hook_args()` (`Python/errors.c:1422`) unconditionally builds its result with

```c
PyObject *args = PyStructSequence_New(&UnraisableHookArgsType);
```

and `PyStructSequence_New()` → `get_type_attr_as_size()` (`Objects/structseq.c:30`) immediately
dereferences the type's dict:

```c
PyObject *v = PyDict_GetItemWithError(_PyType_GetDict(tp), name);
```

`UnraisableHookArgsType` is a per-interpreter builtin structseq type, initialized by
`_PyErr_InitTypes()` (via `_PyStructSequence_InitBuiltin`) during interpreter startup. When a
sub-interpreter's creation fails under OOM *before* that init runs, `tp_dict` is still NULL.
The failure path then calls `Py_EndInterpreter()` → `make_pre_finalization_calls()` →
`wait_for_thread_shutdown()`, which sees the pending `MemoryError` and routes it to
`PyErr_FormatUnraisable()`:

```c
/* wait_for_thread_shutdown(), Python/pylifecycle.c */
PyObject *threading = PyImport_GetModule(&_Py_ID(threading));
if (threading == NULL) {
    if (_PyErr_Occurred(tstate)) {
        handle_thread_shutdown_exception(tstate);   /* -> PyErr_FormatUnraisable -> the NULL type */
    }
    return;
}
```

So `_PyType_GetDict(&UnraisableHookArgsType)` returns NULL, `PyDict_GetItemWithError(NULL, …)`
runs `PyAnyDict_Check(NULL)` → `Py_TYPE(NULL)` and segfaults. The unraisable-reporting path
assumes the `UnraisableHookArgs` type is ready, which is not guaranteed while finalizing a
sub-interpreter whose own initialization failed.

## Suggested fix

Make unraisable reporting robust to an uninitialized `UnraisableHookArgs` type so it falls back
to the plain-stderr report instead of dereferencing NULL. `format_unraisable_v()` already has a
fallback when `make_unraisable_hook_args()` returns NULL, so the minimal fix is to make the
builder fail cleanly:

```c
/* make_unraisable_hook_args(), Python/errors.c */
if (_PyType_GetDict(&UnraisableHookArgsType) == NULL) {
    /* type not initialized (e.g. finalizing a sub-interp whose init failed) */
    return NULL;        /* -> format_unraisable_v() uses its default stderr path */
}
PyObject *args = PyStructSequence_New(&UnraisableHookArgsType);
```

Defensively, `get_type_attr_as_size()` / `PyStructSequence_New()` could also treat a NULL
`_PyType_GetDict(tp)` as an error rather than dereferencing it. (A deeper option is for
`wait_for_thread_shutdown()` not to invoke the structseq-based hook during the finalization of a
partially-initialized interpreter, but the builder-level guard is the smallest robust fix.)

## Notes

- Found by fusil OOM-injection fuzzing (`--oom-fuzz` / `--oom-seq`), vehicle module
  `concurrent.futures.interpreter` (`InterpreterPoolExecutor`). The crash is a worker thread
  creating its sub-interpreter under a windowed allocation failure.
- This is **Face A** of that vehicle. The same vehicle non-deterministically also hits a
  `_PyMem_DebugRawFree` bad-free in the same `_PyXI_NewInterpreter`/`new_interpreter` area —
  that is **OOM-0020** (a distinct defect, "Face B"). Dedup is by the faulting site; this report
  is the `make_unraisable_hook_args`/`PyStructSequence_New` NULL-deref only.
- Build matrix: SIGSEGV on free-threaded debug+ASan, GIL debug+ASan, GIL JIT+ASan, free-threaded
  release, and GIL release — i.e. release-reproducing, not assert-gated.

## Versions

- main (3.16.0a0, commit `1b9fe5c`). Reproduced (reduced `repro.py`) on debug-ft-nojit-asan,
  debug-gil-nojit-asan, debug-gil-jit-asan (SEGV; ASan rc 1) and release-ft-nojit,
  release-gil-nojit (SEGV, rc 139).

---

*Found with [fusil](https://github.com/devdanzin/fusil) OOM-injection fuzzing.*
