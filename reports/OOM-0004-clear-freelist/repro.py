"""
Minimal reproducer: corrupted per-thread object freelist under OOM in the
free-threaded build.

Affected:   CPython 3.16.0a0 (main, commit 15d7406), free-threaded build.
Surfaces:
  * Abort  : assert(freelist->size == 0 || freelist->size == -1) in
             clear_freelist (Objects/object.c:909), reached from the GC's
             _PyObject_ClearFreeLists -> clear_freelist. DEBUG-ONLY assert.
             This is the signature recorded by the original fuzzing vehicles.
  * SEGV   : use-after-free in free_list_items (Objects/listobject.c:68) when
             PyList_New pops a corrupted node off the `lists` freelist whose
             stale ob_item points at freed (0xcd-filled) array memory, then
             list_allocate_array() fails under OOM and Py_DECREF(op) frees the
             dangling pointer. This is what the reduced repro below hits
             deterministically (build-agnostic).
Requires:   a build exposing _testcapi.set_nomemory (debug/test builds).

Run:
    python repro.py
    # crashes during the start=4 iteration (rc 134 abort / rc 139 segv,
    # or rc 1 under ASan)

Deterministic SEGV backtrace (gdb, 3.16_ft_debug_asan) -- identical to the
captured vehicle backtrace:

    #0 _PyMem_DebugCheckAddress   Objects/obmalloc.c:3344   (p = 0xcdcdcdcdcdcdcdc5)
    #3 free_list_items            Objects/listobject.c:68
    #4 list_dealloc               Objects/listobject.c:569
    #7 PyList_New                 Objects/listobject.c:262  (Py_DECREF after alloc fail)
    #8 _PyList_FromStackRefStealOnSuccess Objects/listobject.c:3298

Root cause (Objects/object.c, clear_freelist, L901; Objects/listobject.c,
PyList_New, L248):

    The per-PyThreadState object freelists track `size` alongside the singly
    linked `freelist` chain. Under repeated allocation failure, PyList_New pops
    a list object off the freelist BEFORE the fallible list_allocate_array();
    on failure it Py_DECREF(op)s, sending the object straight back onto the same
    freelist via list_dealloc. This pop/push-on-failure churn desyncs `size`
    from the chain and leaves a node with a stale, dangling ob_item. The next
    PyList_New pops that bad node and frees the dangling ob_item (SEGV); a GC
    freelist sweep that runs first instead trips clear_freelist's size/chain
    assertion (abort).

Likely fix: reset op->ob_item/size/allocated on the freelist-pop path in
PyList_New before any fallible allocation, and reset (not assert) freelist->size
in clear_freelist so a desync cannot corrupt later allocations.
"""
import gc
from _testcapi import set_nomemory, remove_mem_hooks


def go():
    objs = []
    for _ in range(120):
        a = (1.0, 2.0, 3.0)          # tuple + float freelists
        b = [a[0], a[1], a[2]]       # list freelist (PyList_New)
        objs.append(b[0:2])          # slice -> another PyList_New
    gc.collect()                     # GC sweeps freelists -> clear_freelist
    return objs


for start in range(1, 900):          # observed crash at start=4
    set_nomemory(start, 0)           # fail every allocation from #start onward
    try:
        try:
            go()
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
print("no crash", flush=True)
