# Title

Abort/Segfault: negative refcount (`PyStackRef_XCLOSE` -> `Py_DECREF`) in `_PyFrame_ClearLocals` (`Python/frame.c`) when a frame is torn down during exception unwinding under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

When an allocation fails (`MemoryError`) in the middle of a bytecode instruction, the eval loop unwinds the frame through its `exit_unwind` label, which clears the frame's operand stack via `_PyFrame_ClearLocals()`. Under OOM, an opcode error path has left a stale / already-dead `_PyStackRef` on the value stack, so closing it (`PyStackRef_XCLOSE` -> `Py_DECREF`) drives the referenced object's refcount below zero. On the debug build this aborts with `_Py_NegativeRefcount: "object has negative ref count"`; on release builds the assert is compiled out and the underflowed refcount frees a still-live object, producing a later use-after-free **segfault**. The over-decref'd object in the observed crashes is a `MemoryError` instance.

This is the largest crash group in the run (8+ vehicles, all converging on the same site) and the most severe: it is a genuine refcount-underflow / memory-safety bug, not merely a debug assertion.

## Reproducer

`repro.py` keeps the vehicle's heavy module-level setup (it shifts heap/refcount layout so this underflow fires first) and then runs the two crashing OOM sweeps:

```python
import multiprocessing.spawn as sp
from _testcapi import set_nomemory as _set_nomemory, remove_mem_hooks as _remove_mem_hooks

def oom_call(func, *args, **kwargs):
    for _start in range(1000):
        _set_nomemory(_start, 0)
        try:
            try:
                func(*args, **kwargs)
            finally:
                _remove_mem_hooks()
        except MemoryError:
            pass

oom_call(sp._fixup_main_from_name, weird_classes['weird_bytes'])
oom_call(sp._fixup_main_from_path, b"\xF3\xF6\x8B\x4A\xFF\x52\xEC")  # -> runpy.run_path -> OOM unwind
```

`_fixup_main_from_path(bad-bytes)` calls `runpy.run_path()`, which raises `MemoryError` deep in the import/runpy machinery; the exception unwinds frames whose operand stack still holds a now-dead stackref. Reproduces 3/3 on `ft_debug_asan` (SIGABRT) and segfaults on the release builds.

**Minimization: PARTIAL.** Reducing to a bare `runpy.run_path()` / `_fixup_main_from_path()` call instead trips a *sibling* OOM assert first -- `Objects/codeobject.c:2440` `_co_unique_id == _Py_INVALID_UNIQUE_ID` in `code_dealloc` -- a separate finding. Which teardown assert fires first is sensitive to heap/refcount layout, so the full setup is retained. A clean stdlib-only snippet that deterministically drives *this* stackref underflow was not found; the underlying defect is in the eval-loop/opcode error-cleanup, not in any stdlib module.

## Backtrace

```
#9  _Py_NegativeRefcount        Objects/object.c:275       (op = a MemoryError, refcount underflowed)
#10 Py_DECREF                   Include/refcount.h:354
#11 PyStackRef_XCLOSE           Include/internal/pycore_stackref.h:726
#12 _PyFrame_ClearLocals        Python/frame.c:101         (while (sp > locals) PyStackRef_XCLOSE(*sp))
#13 _PyFrame_ClearExceptCode    Python/frame.c:126
#14 clear_thread_frame          Python/ceval.c:1954
#15 _PyEval_EvalFrameDefault    Python/generated_cases.c.h:13908   (LABEL exit_unwind -> _PyEval_FrameClearAndPop)
```

Fatal dump: `object type name: MemoryError`. Identical top frames (#11-#15) confirmed on multiprocessing_spawn, concurrent_futures_process, xml_dom_minidom, _pyrepl_main, importlib_resources, zoneinfo__tzpath, profiling_sampling__sync_coordinator -- the group does **not** split.

## Root cause

`Python/frame.c`, `_PyFrame_ClearLocals` (L92):

```c
void
_PyFrame_ClearLocals(_PyInterpreterFrame *frame)
{
    assert(frame->stackpointer != NULL);
    _PyStackRef *sp = frame->stackpointer;
    _PyStackRef *locals = frame->localsplus;
    frame->stackpointer = locals;
    while (sp > locals) {
        sp--;
        PyStackRef_XCLOSE(*sp);     /* L101: closes every live operand-stack slot */
    }
    Py_CLEAR(frame->f_locals);
}
```

This is correct *only if* `frame->stackpointer` accurately reflects the set of operand-stack slots the frame still owns. The bug is upstream of here: an opcode that can fail under allocation pressure took an error exit *after* it had already consumed (closed / stolen via `PyStackRef_*Steal`) a stack value but *before* it removed that slot from the stack pointer -- or it pushed a borrowed reference that it doesn't own. The dead/stale `_PyStackRef` is then left on the value stack. When `MemoryError` unwinds the frame (`exit_unwind` -> `_PyEval_FrameClearAndPop` -> `clear_thread_frame` -> `_PyFrame_ClearExceptCode` -> `_PyFrame_ClearLocals`), that slot is closed and the object's refcount underflows:

- debug (`Py_REF_DEBUG`): `Py_DECREF` detects refcount < 0 -> `_Py_NegativeRefcount` (`Objects/object.c:275`) -> `_PyObject_AssertFailed` -> abort.
- release: no check; the object is freed while still referenced elsewhere -> use-after-free segfault later.

The MemoryError itself being the over-decref'd object suggests the offending opcode is one that puts the just-raised exception (or a value derived alongside it) onto the stack and mishandles its ownership on the error path (CALL/`*_VECTORCALL` steal paths, `BINARY_OP`, `BUILD_*`, or the `FOR_ITER`/`SEND`/`CLEANUP_THROW` family), or one of the generated `pop_N_error:` / `error:` exit stubs miscounting the live stack depth.

## Suggested fix

Audit the bytecode-handler error/cleanup paths (and the generated `pop_N_error:` / `error:` stubs in `Python/bytecodes.c` / `generated_cases.c.h`) so that on any allocation-failure exit, `frame->stackpointer` exactly matches the set of still-owned stackrefs: every consumed/stolen value must be popped, every leftover value must remain owned. The fix is in the opcode that leaks the stale ref, not in `_PyFrame_ClearLocals` (which must trust the stack pointer). As a debugging aid, the stack-effect invariants could be asserted on the error path before `_PyEval_FrameClearAndPop`.

## Notes

- Found by OOM-injection fuzzing (`_testcapi.set_nomemory`). Largest group in `python-4`.
- **Build matrix:** `ft_debug_asan` -> **abort** (negative-refcount assert). `ft_release` and `upstream` -> **segv** (use-after-free; assert compiled out). `jit` -> **abort**, but at a *sibling* assert in the same `exit_unwind` path: `generated_cases.c.h:13817 "_PyErr_Occurred(tstate)"` -- same teardown machinery, different invariant tripped by JIT dispatch.
- **`concurrent_futures_process`** (filed as a "segfault" vehicle) is **confirmed** part of this group: it hits the negative-refcount assert on `ft_debug_asan` and segfaults 5/5 on both `ft_release` and `upstream` (rc 139). This is the clearest demonstration that the release-build segfault and the debug-build assert are the same underlying refcount underflow.
- **Sibling bug spotted during minimization:** under the same OOM sweep, `runpy.run_path()` / `spawn._fixup_main_from_path()` can instead abort at `Objects/codeobject.c:2440` (`_co_unique_id == _Py_INVALID_UNIQUE_ID` in `code_dealloc`) -- a *different* over-free during code-object teardown under OOM, likely worth a separate id.

## Versions

- main (3.16.0a0), commit 15d7406. Reproduces on free-threaded debug+ASan (abort), free-threaded release and default/GIL release (segfault); JIT build aborts at a sibling assert in the same path.
