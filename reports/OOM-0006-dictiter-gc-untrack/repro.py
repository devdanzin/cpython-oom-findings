"""
Reproducer: _PyObject_GC_UNTRACK assert in dictiter_dealloc under OOM (OOM-0006).

Affected:   CPython 3.16.0a0 (main, commit 15d7406). The C defect is build-agnostic.
Crash:      Objects/dictobject.c:5532: _PyObject_GC_UNTRACK assertion
            "object not tracked by the garbage collector" (object type
            dict_itemiterator) on assertion-enabled builds; SIGSEGV in
            _Py_Dealloc on release builds (NDEBUG strips the assert).
Requires:   a build exposing _testcapi.set_nomemory (debug/test builds).

Backtrace (gdb, ft_debug_asan):
    #9  _PyObject_GC_UNTRACK      Include/internal/pycore_gc.h:254
    #10 dictiter_dealloc          Objects/dictobject.c:5532   (dict_itemiterator, refcnt 0)
    #11 _Py_Dealloc              Objects/object.c:3319
    #12 Py_DECREF                Include/refcount.h:359
    #13 dictiter_new            Objects/dictobject.c:5516   <- Py_DECREF(di), di NOT yet tracked
    #14 PyObject_GetIter         Objects/abstract.c:2825
    #15 _PyEval_GetIter / GET_ITER

Root cause (Objects/dictobject.c, dictiter_new, L5486-5525):

    di = PyObject_GC_New(dictiterobject, itertype);   # L5491: NOT yet GC-tracked
    ...
    if (itertype == &PyDictIterItem_Type || itertype == &PyDictRevIterItem_Type) {
        di->di_result = _PyTuple_FromPairSteal(Py_None, Py_None);  # L5514: fails under OOM
        if (di->di_result == NULL) {
            Py_DECREF(di);     # L5516: di is UNTRACKED -> dictiter_dealloc -> _PyObject_GC_UNTRACK assert
            return NULL;
        }
    }
    _PyObject_GC_TRACK(di);    # L5523: tracking only happens here (too late on the error path)

Only item iterators are affected: they are the only kind whose di_result requires an
allocation between PyObject_GC_New and _PyObject_GC_TRACK.

Likely fix: move _PyObject_GC_TRACK(di) before the _PyTuple_FromPairSteal call (set
di->di_result = NULL first), or PyObject_GC_Del(di) directly on the error path instead
of Py_DECREF(di).

--------------------------------------------------------------------------------
MINIMIZATION STATUS: PARTIAL (best-effort). This standalone stdlib-only sweep does
NOT reproduce by itself. In the warm steady state, PyObject_GC_New(di) is served from
a pymalloc pool and tuple_alloc(2) from the size-2 tuple freelist, so neither
allocation in iter(d.items()) ever consults the failing (hooked) allocator -- the
crash window (GC_New succeeds, FromPairSteal fails) is never entered. Forcing
fresh-pool churn (fresh dicts each round) trips a *different* OOM assertion first
(_Py_NegativeRefcount in PyStackRef_XCLOSE, pycore_stackref.h:726, from GET_ITER's
error path). The reliable reproducer is the fuzzing VEHICLE, whose large prelude
shifts the global heap/freelist state so the dictiter window aligns:

    ~/crashers/python-4/asyncio_runners-assertion/source.py   (rc=134 on ft_debug_asan/jit)

Run that file under an assertion build to observe the abort. The sweep below is kept
as documentation of the attempted minimization (it exits cleanly on a warm build).
--------------------------------------------------------------------------------
"""
import sys
from _testcapi import set_nomemory, remove_mem_hooks

d = {1: 1, 2: 2, 3: 3}

for start in range(200):
    set_nomemory(start, 0)             # fail every allocation from #start onward
    try:
        try:
            # dictiter_new(PyDictIterItem_Type): allocates di (GC_New), then
            # _PyTuple_FromPairSteal for di_result. If that tuple alloc fails while di
            # is still untracked, Py_DECREF(di) -> dictiter_dealloc ->
            # _PyObject_GC_UNTRACK assert. (Does NOT trip standalone on a warm build --
            # see MINIMIZATION STATUS above; use the vehicle source.py instead.)
            it = iter(d.items())
            next(it, None)
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass

print("no standalone crash (expected: warm freelists); reproduce via the vehicle source.py",
      file=sys.stderr)
