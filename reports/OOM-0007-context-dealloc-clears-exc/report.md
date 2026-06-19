# Title

Fatal: `_Py_Dealloc: Deallocator of type 'Context' cleared the current exception` — `context_tp_dealloc` (`Python/context.c`) does not preserve the pending exception under OOM

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Under memory pressure, a `contextvars.Context` can be deallocated while an exception (a `MemoryError` raised mid-operation) is in flight — e.g. the last reference is dropped while a frame is unwinding. `context_tp_dealloc()` runs its teardown (`PyObject_ClearWeakRefs` + `context_tp_clear`, which decrefs `ctx_prev` and the `ctx_vars` HAMT and all stored ContextVar values) **without saving/restoring `tstate->current_exception`**. That teardown clears the pending exception, which trips the gh-89373 debug invariant in `_Py_Dealloc` and aborts with `Fatal Python error: _Py_Dealloc: Deallocator of type 'Context' cleared the current exception`. This is a fatal abort (debug builds only — the invariant is `Py_DEBUG`-gated); on release builds the same defect is a silent corruption of the error indicator.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle, then cleaned; deterministic,
re-verified). A Context is deallocated with a pending exception under OOM.

```python
import faulthandler, importlib.metadata
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(40):
    set_nomemory(start)
    try:
        importlib.metadata.metadata("f")
    except BaseException:
        pass
print("done, no crash")
```

The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
Fatal Python error: _Py_Dealloc: Deallocator of type 'Context' cleared the current exception
Stack (most recent call first):
  File ".../Lib/importlib/metadata/__init__.py", line 1081 in distributions
  File ".../Lib/importlib/metadata/__init__.py", line 1123 in entry_points

# C path (gdb, break on _Py_FatalErrorFormat):
#1 _Py_Dealloc            Objects/object.c:3338   err="...cleared the current exception", tp_name=="Context"
#4 cell_dealloc           Objects/cellobject.c:81 Py_XDECREF(op->ob_ref)  (ob_ref == the Context)
#8 _PyFrame_ClearLocals   Python/frame.c:101      frame unwinding under pending MemoryError
#10 clear_thread_frame    Python/ceval.c:1954
#11 _PyEval_EvalFrameDefault
```

`old_exc` (saved by `_Py_Dealloc`) = the pending `MemoryError`; `tstate->current_exception` = `NULL` after the `Context` `tp_dealloc` → "cleared".

## Root cause

`Python/context.c`, `context_tp_dealloc` (L535-546):

```c
static void
context_tp_dealloc(PyObject *self)
{
    _PyObject_GC_UNTRACK(self);
    PyContext *ctx = _PyContext_CAST(self);
    if (ctx->ctx_weakreflist != NULL) {
        PyObject_ClearWeakRefs(self);     /* runs weakref callbacks */
    }
    (void)context_tp_clear(self);         /* Py_CLEAR(ctx_prev); Py_CLEAR(ctx_vars) -> HAMT + value decrefs */
    _Py_FREELIST_FREE(contexts, self, Py_TYPE(self)->tp_free);
}
```

`context_tp_clear()` decrefs the `ctx_vars` HAMT, which decrefs every stored ContextVar value; that arbitrary teardown (and/or a weakref callback) can clear or normalize `tstate->current_exception`. Unlike `PyObject_ClearWeakRefs` itself (which carefully saves/restores via `PyErr_GetRaisedException`/`PyErr_SetRaisedException`), `context_tp_dealloc` performs **no** exception save/restore — there is no `PyErr_GetRaisedException`/`PyErr_Fetch` anywhere in `Python/context.c`. A `tp_dealloc` must leave `tstate->current_exception` unchanged (gh-89373); this one does not.

## Suggested fix

Bracket the teardown in `context_tp_dealloc` with exception save/restore, the standard pattern for deallocs that run arbitrary decref cascades:

```c
static void
context_tp_dealloc(PyObject *self)
{
    _PyObject_GC_UNTRACK(self);
    PyContext *ctx = _PyContext_CAST(self);

    PyObject *exc = PyErr_GetRaisedException();   /* preserve in-flight exception */

    if (ctx->ctx_weakreflist != NULL) {
        PyObject_ClearWeakRefs(self);
    }
    (void)context_tp_clear(self);

    PyErr_SetRaisedException(exc);                /* restore before returning */

    _Py_FREELIST_FREE(contexts, self, Py_TYPE(self)->tp_free);
}
```

(The same hardening likely applies to `contextvar_tp_dealloc` / `token_tp_dealloc`, whose `tp_clear` paths also decref user objects.)

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). Two independent vehicles, identical fatal message and (vehicle 1) identical Python stack: `importlib.metadata.entry_points` and `importlib.metadata.diagnose.run`. **Debug-only signature:** the `_Py_Dealloc` invariant is `#ifdef Py_DEBUG`, so the fatal appears only on debug builds (ft_debug_asan, jit); on release builds (ft_release, upstream) the check is compiled out and the same OOM vehicle instead surfaces an unrelated downstream segfault. Distinct from OOM-0002 (`PyContextVar_Set` `Py_DECREF(NULL)`): that is a NULL-decref segfault in `cv.set()`; this is a dealloc-time exception-state violation. Minimization: partial — vehicle-confirmed, no minimal stdlib trigger isolated.

Related but likely distinct: other `Deallocator of type 'X' cleared the current exception` fatals seen in this fuzzing run (`_StoreAction`, `UnknownHandler`, `ProxyHandler`, `LogRecord`) are different types and may have separate (or a shared generic) root cause — triaged separately, not folded in here.

## Versions

- main (3.16.0a0), commit 15d7406. Reproduces (fatal) on free-threaded debug+ASan and JIT debug builds; not observed as this signature on release builds (invariant compiled out).
