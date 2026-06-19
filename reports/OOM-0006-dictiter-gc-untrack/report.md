# Title

Abort/Segfault: `_PyObject_GC_UNTRACK` assert in `dictiter_dealloc` (`Objects/dictobject.c`) when `dictiter_new()` decref's an untracked item-iterator under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Creating a **dict item-iterator** (`iter(d.items())`, reversed items) while allocations are failing aborts on a debug build with `Objects/dictobject.c:5532: _PyObject_GC_UNTRACK: Assertion "_PyObject_GC_IS_TRACKED(op)" failed: object not tracked by the garbage collector` (object type `dict_itemiterator`). `dictiter_new()` allocates the iterator with `PyObject_GC_New` but only calls `_PyObject_GC_TRACK(di)` at the very end; if the intermediate `_PyTuple_FromPairSteal()` (for `di_result`) fails under OOM, the function does `Py_DECREF(di)` on the still-untracked object, and `dictiter_dealloc()` unconditionally calls `_PyObject_GC_UNTRACK(di)`. On release builds (NDEBUG) the assert is compiled out and the un-tracking corrupts the GC list, segfaulting later in `_Py_Dealloc`.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle, then cleaned; deterministic,
re-verified). Strptime parsing under OOM corrupts the per-thread object freelist.

```python
import faulthandler, _strptime
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(60):
    set_nomemory(start)
    try:
        _strptime._strptime("", "")
    except BaseException:
        pass
print("done, no crash")
```

The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
#8  _PyObject_AssertFailed                          Objects/object.c:3278
#9  _PyObject_GC_UNTRACK                            Include/internal/pycore_gc.h:254   <- assert: !_PyObject_GC_IS_TRACKED
#10 dictiter_dealloc (self=dict_itemiterator)       Objects/dictobject.c:5532
#11 _Py_Dealloc                                     Objects/object.c:3319
#12 Py_DECREF                                       Include/refcount.h:359
#13 dictiter_new (itertype=PyDictIterItem_Type)     Objects/dictobject.c:5516          <- Py_DECREF(di) after di_result alloc fails
#14 PyObject_GetIter                                Objects/abstract.c:2825
#15 _PyEval_GetIter                                 Python/ceval.c:1142
#16 _PyEval_EvalFrameDefault (GET_ITER)             Python/generated_cases.c.h:6950
```

Faulting object: a freshly-allocated, **never-tracked** `dict_itemiterator`
(`object refcount : 0`, `object type name: dict_itemiterator`) being deallocated from
inside its own constructor's error path.

## Root cause

`Objects/dictobject.c`, `dictiter_new()` (L5486-5525):

```c
di = PyObject_GC_New(dictiterobject, itertype);   /* L5491: allocated, NOT yet GC-tracked */
if (di == NULL) { return NULL; }
di->di_dict = (PyDictObject*)Py_NewRef(dict);
...
if (itertype == &PyDictIterItem_Type ||
    itertype == &PyDictRevIterItem_Type) {
    di->di_result = _PyTuple_FromPairSteal(Py_None, Py_None);   /* L5514: can fail (OOM) */
    if (di->di_result == NULL) {
        Py_DECREF(di);                                          /* L5516: di is UNTRACKED -> dealloc asserts */
        return NULL;
    }
}
else {
    di->di_result = NULL;
}
_PyObject_GC_TRACK(di);                                         /* L5523: tracking happens only here */
return (PyObject *)di;
```

`dictiter_dealloc()` (L5527) unconditionally untracks (correct for the normal lifecycle,
since "UnTrack is needed before calling any callbacks", bpo-31095):

```c
static void dictiter_dealloc(PyObject *self) {
    dictiterobject *di = (dictiterobject *)self;
    _PyObject_GC_UNTRACK(di);          /* L5532: asserts the object IS tracked */
    Py_XDECREF(di->di_dict);
    Py_XDECREF(di->di_result);
    PyObject_GC_Del(di);
}
```

`_PyObject_GC_UNTRACK` (`Include/internal/pycore_gc.h:254`) asserts
`_PyObject_GC_IS_TRACKED(op)`. On the `di_result == NULL` error path the iterator is
deallocated *before* it was ever tracked, so the assert fires (debug) or the GC
freelist is corrupted (release -> later segfault in `_Py_Dealloc`).

This only affects **item** iterators (`dict_itemiterator` / `dict_reverseitemiterator`),
because they are the only ones whose `di_result` requires an allocation between
`PyObject_GC_New` and `_PyObject_GC_TRACK` (matching every observed `object type name:
dict_itemiterator`).

## Suggested fix

Track the iterator before the only fallible allocation, or use a manual free that does
not assume tracking on the error path. Cleanest fix -- move `_PyObject_GC_TRACK(di)`
*before* the `_PyTuple_FromPairSteal` call (initialize `di->di_result = NULL` first so
`dictiter_dealloc`'s `Py_XDECREF` is safe), so the standard `Py_DECREF(di)` /
`dictiter_dealloc` path is valid:

```c
    di->di_result = NULL;
    _PyObject_GC_TRACK(di);                     /* track once, before any fallible alloc */
    if (itertype == &PyDictIterItem_Type || itertype == &PyDictRevIterItem_Type) {
        di->di_result = _PyTuple_FromPairSteal(Py_None, Py_None);
        if (di->di_result == NULL) {
            Py_DECREF(di);                       /* now di is tracked: dealloc is valid */
            return NULL;
        }
    }
    return (PyObject *)di;
```

Alternative (keep tracking last): free the untracked object directly instead of via
the GC-untracking dealloc:

```c
    if (di->di_result == NULL) {
        Py_DECREF((PyObject *)dict);   /* matching the Py_NewRef above */
        PyObject_GC_Del(di);           /* untracked: free directly, no UNTRACK assert */
        return NULL;
    }
```

## Notes

- Found by OOM-injection fuzzing (`_testcapi.set_nomemory`). The assert fires **only**
  on builds with assertions (debug). Release builds strip the assert (NDEBUG) and
  instead corrupt the GC list, segfaulting later in `_Py_Dealloc` -- which is why the
  `zipapp` vehicle was originally labeled "segmentation_fault" yet trips the identical
  `dictiter_dealloc`/`_PyObject_GC_UNTRACK` assert on the debug build (confirmed).
- Vehicles (all confirmed on `ft_debug_asan`, all `dict_itemiterator`):
  `asyncio_runners-assertion` (representative, via `weakref.py:240` `dict.items()`),
  `re-assertion-sigabrt` (via `re/_compiler.py:775`), and
  `zipapp-segmentation_fault` (segv on release+ASan upstream; same assert on debug).
- **Minimization: partial.** A stdlib-only `iter(d.items())` sweep does not reproduce:
  in the warm steady state neither `PyObject_GC_New(di)` (pymalloc) nor `tuple_alloc(2)`
  (size-2 tuple freelist) consults the hooked allocator, so the failure window is never
  entered. Forcing fresh-pool/freelist churn (fresh dicts per round) trips a *different*
  OOM bug first (`_Py_NegativeRefcount` assert in `PyStackRef_XCLOSE`,
  `pycore_stackref.h:726`, from `GET_ITER` error handling). The vehicle remains the
  reliable reproducer. The C defect itself is build-agnostic and unambiguous.
- Same family as OOM-0001/OOM-0002: an error path acting on a partially-constructed
  object whose intermediate allocation/sequencing was left unchecked under OOM.

## Versions

- main (3.16.0a0, commit 15d7406). Reproduces (via the vehicle): `ft_debug_asan` ->
  abort (assert), `jit` -> abort (assert), `upstream` (release+ASan) -> segv in
  `_Py_Dealloc`. `ft_release` -> no crash in this run (NDEBUG; assert stripped, segv did
  not manifest on that path). Long-standing code; 3.13-3.15 likely affected (unverified).
