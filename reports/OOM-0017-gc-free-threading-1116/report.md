# Abort: `assert(gc_get_refs(op) >= 0)` "refcount is too small" in `validate_gc_objects` (`Python/gc_free_threading.c:1116`) during finalization GC, after an OOM sweep over `socket.recv_fds` corrupts the deferred refcount of the `array.array` type

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

A dense OOM sweep that repeatedly drives `socket.recv_fds()` (which does `import array; array.array("i")` then `recvmsg`) leaves the **`array.array` type object** with a reference count that is smaller than the number of live references to it. The miscount is invisible until the interpreter shuts down: `_Py_Finalize` -> `PyGC_Collect` runs the free-threaded cyclic GC, whose `update_refs`/`visit_decref` tally drives the type's `gc_refs` below zero, and the debug-only consistency assertion `gc_get_refs(op) >= 0` in `validate_gc_objects` (`Python/gc_free_threading.c:1116`) aborts the process. SIGABRT, deterministic (rc 134).

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the socket fuzz vehicle). Requires a
free-threaded debug build (`PYTHON_GIL=0`); reliable (~75%/run, aborts within a couple of
runs). See `repro.py`:

```python
import socket
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(259):
    set_nomemory(start)
    try:
        try:
            socket.recv_fds(0, 0, 0)   # internally: import array; array.array("i")
        finally:
            remove_mem_hooks()
    except:
        pass
```

The abort fires during interpreter *shutdown* GC, after the loop completes. shrinkray
**disproved** the earlier belief that the fuzzer boilerplate's allocation baseline was
load-bearing: the bare `socket.recv_fds(0, 0, 0)` sweep reproduces on its own (a pure
`array.array("i")` sweep still does not — the corrupting path is specifically `recv_fds`'s
construct-array-then-fail under OOM). Minimization **complete**; the full vehicle is
preserved as `vehicle_source.py`.

## Backtrace

```
#9  validate_gc_objects     Python/gc_free_threading.c:1115   <- assert gc_get_refs(op) >= 0 (L1116)
#10 _mi_heap_area_visit_blocks  Objects/mimalloc/heap.c:569
#16 gc_visit_heaps_lock_held Python/gc_free_threading.c:390
#18 deduce_unreachable_heap  Python/gc_free_threading.c:1452
#20 gc_collect_main          Python/gc_free_threading.c:2257
#21 PyGC_Collect             Python/gc_free_threading.c:2559
#22 _Py_Finalize             Python/pylifecycle.c:2487
#23 Py_RunMain               Modules/main.c:798
```

Fatal message:

```
Python/gc_free_threading.c:1116: validate_gc_objects: Assertion "gc_get_refs(op) >= 0" failed: refcount is too small
object refcount : 1152921504606847026     (0x1000000000000032; deferred-refcount base, drifted ~ -4)
object type name: type
object repr     : <class 'array.array'>   (the corrupted object is the array.array TYPE)
Python runtime state: finalizing          (empty Python stack: body finished, crash is in shutdown GC)
```

The object is not NULL or freed: it is a live, deferred-refcounted **type** whose refcount tally is too small relative to the references the GC finds. The reported `ob_refcnt` is `_Py_REF_DEFERRED` (`PY_SSIZE_T_MAX/8`) plus a small merged-shared component, drifted a few counts below the healthy baseline.

## Root cause

The `array.array` type uses **deferred reference counting** (free-threaded builds). `socket.recv_fds()` constructs `array.array("i")`; under OOM that construction frequently fails part-way:

`Modules/arraymodule.c`, `newarrayobject()` (L755):

```c
    op = (arrayobject *) type->tp_alloc(type, 0);   /* L770: takes a (deferred) ref to `type` */
    ...
    op->ob_item = PyMem_NEW(char, nbytes);          /* L782: fails under OOM */
    if (op->ob_item == NULL) {
        Py_DECREF(op);                              /* L784: -> array_dealloc */
        return PyErr_NoMemory();
    }
```

`array_dealloc()` (L837) unconditionally drops a reference to the type:

```c
    tp->tp_free(op);
    Py_DECREF(tp);                                  /* L848 */
```

Across the dense OOM sweep this alloc-then-free-on-error cycle runs many times. The interaction between the **deferred** reference `tp_alloc` records for the type and the **real** `Py_DECREF(tp)` in `array_dealloc` leaves the `array.array` type's shared/deferred refcount a few counts short of the number of live references to it. The corruption is silent at runtime (the deferred base is enormous), and only the cyclic GC notices: `update_refs` (`gc_free_threading.c:973`) seeds `gc_refs` with the object's refcount, then `tp_traverse`/`visit_decref` subtract one per internal reference; with the type's refcount too small, `gc_refs` underflows below zero and `validate_gc_objects` (L1116) asserts. It is a refcount-balance defect (over-release / deferred-vs-strong mismatch on a type under OOM), not a use-after-free or a NULL deref.

## Suggested fix

This is an allocator-error-path refcount-balance bug, not a missing NULL check. The fix is to make the type-reference accounting consistent on the construction error path so the `array.array` type is not net under-counted when `array.array()` fails under OOM. Concretely, audit the pairing between the deferred reference taken by `PyType_GenericAlloc`/`tp_alloc` for a heaptype instance and the unconditional `Py_DECREF(tp)` in `array_dealloc` (`arraymodule.c:848`) on the partial-construction path (`newarrayobject`, L770/L784), and ensure exactly one net reference is taken and released. (The defect is build-agnostic; the FT GC assertion at `gc_free_threading.c:1116` and the GIL GC assertion at `gc.c:96` are merely the two debug detectors of the same imbalance.) The catalog-level fix may belong in the deferred-refcount handling for heaptype instances rather than in `arraymodule.c` alone.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). The abort fires during **interpreter finalization GC**, long after the call that corrupted the count, so the faulthandler Python stack is empty on the representative vehicle. The corrupted object is the `array.array` *type*, surfaced via `socket.recv_fds`/`send_fds` (both `import array`).

Build matrix:
- **ft_debug_asan**: abort at `gc_free_threading.c:1116` (`validate_gc_objects`, rc 134).
- **jit** (debug, GIL build): abort at `Python/gc.c:96` (`gc_decref: gc_get_refs(g) > 0`, rc 134) -- the **same underlying refcount-too-small bug** detected by the classic GC's debug assertion at a different file:line.
- **ft_release** and **upstream**: assertions compiled out (`-DNDEBUG`); both exit cleanly (rc 0). The refcount imbalance is latent there (a deferred-refcount hazard on the type).

Per the OOM-catalog convention for assert-based aborts, the non-debug builds (`ft_release`, `upstream`) are recorded as `n/a`; `jit` is recorded as its own abort site (`gc.c:96`).

Three fuzzer vehicles, all in the `socket` target driving `recv_fds`/`send_fds` under OOM, abort at the identical `validate_gc_objects` / `gc_get_refs(op) >= 0` assertion on the FT debug build.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build at `gc_free_threading.c:1116` and on the jit debug build at `gc.c:96`. ft_release/upstream: assertion compiled out (`n/a`, clean exit).
