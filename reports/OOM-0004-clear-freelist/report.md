# Abort/Segfault: corrupted per-thread object freelist under MemoryError — `assert(freelist->size == 0 || freelist->size == -1)` in `clear_freelist` (`Objects/object.c:909`), surfacing as a use-after-free `free_list_items` in `PyList_New` (free-threaded build)

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Under sustained allocation failure the free-threaded build's per-`PyThreadState` object freelists become internally inconsistent: the `size` counter and the actual `freelist` chain disagree. This corruption surfaces two ways from the same root: (1) the GC's freelist sweep aborts on `assert(freelist->size == 0 || freelist->size == -1)` in `clear_freelist` (`Objects/object.c:909`) — the recorded crash for all three vehicles — and (2) a subsequent `PyList_New` pops a bogus "list" off the corrupted `lists` freelist whose stale `ob_item` points at already-freed (`0xcd...`-filled) array memory; when the immediately-following `list_allocate_array()` fails under OOM, the cleanup `Py_DECREF(op)` calls `free_list_items()` on that dangling pointer -> use-after-free SEGV in `_PyMem_DebugFree`. The assertion is debug-only (`NDEBUG` drops it), but the underlying freelist corruption is build-agnostic and crashes release, JIT and upstream builds too.

## Reproducer

```python
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

for start in range(1, 900):          # crashes at start=4
    set_nomemory(start, 0)           # fail every allocation from #start onward
    try:
        try:
            go()
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
```

Deterministic at `start=4` on the free-threaded debug+ASan build, and also crashes (SEGV) on free-threaded release, JIT, and upstream. A single `set_nomemory(0,0)` does not suffice — the budget has to let the early freelist pushes/pops succeed and then fail mid-sequence, hence the sweep.

The original fuzzing vehicles instead drained/realloc'd enough lists that the corruption surfaced one step earlier, inside the GC's `clear_freelist`, producing the `Objects/object.c:909` assertion abort (see the recorded faulthandler stack in `backtrace.txt`). Same defect, different surface.

## Backtrace

Deterministic SEGV surface from the reduced reproducer (gdb, `3.16_ft_debug_asan`, commit 15d7406) — byte-identical to the captured vehicle backtrace:

```
#0 _PyMem_DebugCheckAddress   Objects/obmalloc.c:3344    (p = 0xcdcdcdcdcdcdcdc5  <- freed-fill)
#1 _PyMem_DebugRawFree        Objects/obmalloc.c:3166
#2 _PyMem_DebugFree           Objects/obmalloc.c:3316
#3 free_list_items            Objects/listobject.c:68    (PyMem_Free(dangling ob_item))
#4 list_dealloc               Objects/listobject.c:569
#5 _Py_Dealloc               Objects/object.c:3319
#6 Py_DECREF                  Include/refcount.h:359
#7 PyList_New                 Objects/listobject.c:262   (Py_DECREF(op) after list_allocate_array fail)
#8 _PyList_FromStackRefStealOnSuccess Objects/listobject.c:3298
```

Recorded abort surface (faulthandler, original `tarfile` vehicle):

```
python: Objects/object.c:909: void clear_freelist(struct _Py_freelist *, int, freefunc):
        Assertion `freelist->size == 0 || freelist->size == -1' failed.
Fatal Python error: Aborted
  ... _Py_HandlePending -> GC -> _PyObject_ClearFreeLists -> clear_freelist
```

## Root cause

`Objects/object.c`, `clear_freelist` (L901):

```c
static void
clear_freelist(struct _Py_freelist *freelist, int is_finalization, freefunc dofree)
{
    void *ptr;
    while ((ptr = _PyFreeList_PopNoStats(freelist)) != NULL) {   // drains chain
        dofree(ptr);
    }
    assert(freelist->size == 0 || freelist->size == -1);          // L909: size desynced -> abort
    assert(freelist->freelist == NULL);
    ...
}
```

`_PyFreeList_Push`/`_PyFreeList_PopNoStats` (`Include/internal/pycore_freelist.h`) keep `fl->size` in lockstep with the singly-linked `fl->freelist` chain (the "next" pointer is stored in the first word of each freed object). The `clear_freelist` loop pops until the chain is NULL and then asserts `size == 0`. The abort means `size` no longer matches the chain length: the chain terminated (or was diverted) before `size` reached zero.

Two ingredients, both triggered by the OOM injection in the free-threaded build:

1. **Freelist objects are not "next"-cleared on the failure path.** In `PyList_New` (`Objects/listobject.c:248`) the list object is popped from the freelist *before* the size-dependent `list_allocate_array()` runs. When that allocation fails under OOM, the cleanup is `Py_DECREF(op)` (L262), so `op` goes straight back through `list_dealloc` -> `_Py_FREELIST_FREE(lists, op, ...)` (L573) and back onto the same freelist. The repeated pop/push-on-failure churn under a failing allocator is where `size` and the chain drift apart, leaving a node whose stale `ob_item` (L266 was never reached) still points at a freed array.

2. **A later consumer trusts the desynced freelist.** The very next `PyList_New` pops that bad node; with `op->ob_item` dangling and `list_allocate_array` again failing, `Py_DECREF(op)` reaches `free_list_items(op->ob_item, ...)` on freed (`0xcd`) memory -> use-after-free. If a GC sweep runs first instead, `clear_freelist` trips its `size`/chain assertion.

(The assertion is compiled out under `NDEBUG`, which is why release/JIT/upstream don't abort there — but they still crash on the same corruption, as a SEGV.)

## Suggested fix

The robust fix is to make freelist accounting self-healing and to stop trusting `size` independently of the chain. Concretely:

- In `clear_freelist`, drive the loop and the counter off the *chain* and reset `size` unconditionally instead of asserting it, so a desync can't corrupt later allocations:

```c
    void *ptr;
    while ((ptr = _PyFreeList_PopNoStats(freelist)) != NULL) {
        dofree(ptr);
    }
    assert(freelist->freelist == NULL);
    freelist->size = is_finalization ? -1 : 0;   /* reset, don't assert size */
```

- More importantly, fix the producer: in `PyList_New` (`listobject.c:248`), reset `op->ob_item = NULL` (and `Py_SET_SIZE(op, 0); op->allocated = 0;`) on the freelist-pop path *before* the fallible `list_allocate_array()`, so the OOM `Py_DECREF(op)` cleanup never sees a stale `ob_item`:

```c
    PyListObject *op = _Py_FREELIST_POP(PyListObject, lists);
    if (op == NULL) {
        op = PyObject_GC_New(PyListObject, &PyList_Type);
        if (op == NULL) {
            return NULL;
        }
    }
    op->ob_item = NULL;          /* defensive: pop'd object may carry stale state */
    Py_SET_SIZE(op, 0);
    op->allocated = 0;
```

The deeper invariant to audit is every `_Py_FREELIST_POP` / `_Py_FREELIST_FREE` pair on a fallible allocation path: an object must be in a clean, decref-safe state before any allocation that can fail under OOM, since the failure cleanup pushes it back onto the freelist.

## Notes

Found by OOM-injection fuzzing (`_testcapi.set_nomemory`). Free-threading-specific in its *abort* surface (the `clear_freelist` assert and the per-`PyThreadState` freelist machinery are `Py_GIL_DISABLED`-only), but the reduced reproducer crashes all four local builds (debug+ASan abort/SEGV, release SEGV, JIT SEGV, upstream SEGV), so the underlying freelist corruption is not debug-only. Three vehicles in `python-4/` recorded the identical `Objects/object.c:909` assertion; re-running any of them now non-deterministically lands on the sibling `PyList_New`/`free_list_items` use-after-free SEGV instead — confirming a single shared root cause. Distinct from the `_co_unique_id` (`codeobject.c:2440`) assertion that the same vehicles can also hit; that is a separate FT unique-id-pool invariant, not this freelist one.

## Versions

- main (3.16.0a0, commit 15d7406). Reproduced (reduced repro `repro.py`) on free-threaded debug+ASan (SEGV; abort on the vehicle's `clear_freelist` surface), free-threaded release (SEGV), JIT (SEGV), and upstream (SEGV).
