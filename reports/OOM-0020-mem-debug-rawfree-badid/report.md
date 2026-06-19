# Title

Fatal error: `_PyMem_DebugRawFree: bad ID` in `free_threadstate` (`Python/pystate.c`) when sub-interpreter thread-state setup fails under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Creating a sub-interpreter (`concurrent.interpreters.create` -> `_interpreters.create` -> `Py_NewInterpreterFromConfig`) under OOM aborts the whole process with `Fatal Python error: _PyMem_DebugRawFree: bad ID: Allocated using API ' ', verified using API 'r'`. On free-threaded builds, `new_threadstate()` hands out the interpreter's *embedded* `_initial_thread` (preallocated, never heap-allocated). If the free-threaded-only `_Py_qsbr_reserve()` / `_Py_ReserveTLBCIndex()` allocation fails under OOM, the cleanup path calls `free_threadstate()`, whose `tstate == &interp->_initial_thread` identity check reads `interp` from the still-zeroed `tstate->base.interp` (NULL). The check therefore compares against `&((PyInterpreterState*)NULL)->_initial_thread` (a bogus offset), evaluates false, and the code wrongly `PyMem_RawFree()`s the embedded thread state. The debug allocator detects the never-tagged block and aborts.

## Reproducer

```python
import _interpreters, _testcapi
_testcapi.set_nomemory(29, 0)   # fail every allocation from #29 onward
try:
    _interpreters.create(reqrefs=True)   # new sub-interp; tlbc/qsbr reserve fails -> free_threadstate -> bad ID
finally:
    try:
        _testcapi.remove_mem_hooks()
    except Exception:
        pass
```

Deterministic at `start=29` for this exact (import-free) snippet on the free-threaded debug+ASan build (5/5 aborts, rc 134). The OOM budget must be large enough that the interpreter/obmalloc state is built and `alloc_threadstate()` takes the preallocated `_initial_thread`, but small enough that the subsequent free-threaded-only `_Py_ReserveTLBCIndex()`/`_Py_qsbr_reserve()` allocation fails. The exact `start` is sensitive to surrounding allocations: the shipped `repro.py` (which adds an `import sys` + `int(sys.argv[1])` preamble) defaults to `31` (10/10), and the original fuzzer vehicles hit it at `30`. The underlying defect is allocation-index-agnostic.

## Backtrace

```
#8  _PyMem_DebugCheckAddress   Objects/obmalloc.c:3347   <- "bad ID: Allocated using API ' ', verified using API 'r'"
#9  _PyMem_DebugRawFree        Objects/obmalloc.c:3166
#10 free_threadstate          Python/pystate.c:1527     <- PyMem_RawFree(tstate) on the embedded _initial_thread
#11 new_threadstate           Python/pystate.c:1668     <- cleanup after _Py_qsbr_reserve()/_Py_ReserveTLBCIndex() fail under OOM
#12 new_interpreter           Python/pylifecycle.c:2728 <- _PyThreadState_New(interp, _PyThreadState_WHENCE_INIT)
#13 _PyXI_NewInterpreter      Python/crossinterp.c:3269
#14 _interpreters_create_impl Modules/_interpretersmodule.c:878
```

`(gdb) frame 10` confirms the freed object is the embedded `_initial_thread`, not a heap block:

```
print tstate                          -> 0x7bffb41487e0   (the embedded _initial_thread)
print tstate->base.interp             -> 0x0              (NULL: never set by init_interpreter)
print &interp->_initial_thread        -> 0x387a0          (== &((PyInterpreterState*)NULL)->_initial_thread, just the field offset)
print tstate == &interp->_initial_thread -> 0             (FALSE -> falls into the PyMem_RawFree else-branch)
```

The freed block is the interpreter-embedded `_initial_thread` (zeroed by the interpreter's calloc, so its debug API-id byte is `' '`/`0x00`), wrongly passed to `PyMem_RawFree`. This is a bad free of a non-heap pointer, not a use-after-free.

## Root cause

`Python/pystate.c`. `init_interpreter()` (L568) registers the embedded thread state as preallocated:

```c
    interp->threads.preallocated = &interp->_initial_thread;
```

but never sets `interp->_initial_thread.base.interp = interp`. `alloc_threadstate()` (L1498) then hands this preallocated object out:

```c
    tstate = _Py_atomic_exchange_ptr(&interp->threads.preallocated, NULL);   /* == &interp->_initial_thread */
```

In `new_threadstate()` the free-threaded-only reservations can fail under OOM, and each calls `free_threadstate(tstate)` (L1666-1675):

```c
#ifdef Py_GIL_DISABLED
    Py_ssize_t qsbr_idx = _Py_qsbr_reserve(interp);
    if (qsbr_idx < 0) {
        free_threadstate(tstate);          /* L1668 */
        return NULL;
    }
    int32_t tlbc_idx = _Py_ReserveTLBCIndex(interp);
    if (tlbc_idx < 0) {
        free_threadstate(tstate);          /* L1673 */
        return NULL;
    }
#endif
```

`free_threadstate()` (L1512) recovers `interp` from the thread state itself and uses it for the "is this the embedded thread state?" identity check:

```c
    PyInterpreterState *interp = tstate->base.interp;   /* L1514: NULL here */
    ...
    if (tstate == &interp->_initial_thread) {           /* L1520: tstate == &((NULL)->_initial_thread) -> FALSE */
        reset_threadstate(tstate);
        ...
    }
    else {
        PyMem_RawFree(tstate);                          /* L1527: frees the embedded, non-heap _initial_thread */
    }
```

At this point `tstate->base.interp` is still `NULL` (zeroed by the interpreter calloc; it is only set later, in `init_threadstate()` at L1558, which runs *after* the reservations). So `&interp->_initial_thread` degenerates to the struct's field offset (`0x387a0`), the identity check is false, and `PyMem_RawFree()` is handed a pointer that was never returned by the raw allocator. On the debug build `_PyMem_DebugRawFree` detects the untagged block (`bad ID`) and `Py_FatalError`s; on the free-threaded release build the same bad free corrupts the heap and segfaults.

## Suggested fix

Make `free_threadstate()` not depend on `tstate->base.interp` being initialized, or initialize that field for the preallocated thread state. Either set the back-pointer when registering the preallocated tstate in `init_interpreter()`:

```c
    interp->_initial_thread.base.interp = interp;          /* before publishing it as preallocated */
    interp->threads.preallocated = &interp->_initial_thread;
```

or, more robustly, have `free_threadstate()` recover the embedded thread state without trusting `tstate->base.interp` (e.g. compare against the preallocated slot, or pass `interp` in explicitly). The reservation-failure cleanup in `new_threadstate()` must never `PyMem_RawFree()` the interpreter-embedded `_initial_thread`.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Free-threading-specific: the failing `_Py_qsbr_reserve()` / `_Py_ReserveTLBCIndex()` reservations and their `free_threadstate()` cleanup are gated on `#ifdef Py_GIL_DISABLED`, so GIL-enabled builds never reach this path.

Build matrix:
- **ft_debug_asan** (free-threaded debug+ASan): `fatal` -- `_PyMem_DebugRawFree: bad ID` abort at `pystate.c:1527`. This is the authoritative crash.
- **ft_release** (free-threaded, NDEBUG): `segfault` -- the debug `bad ID` check is compiled out, so the bogus `PyMem_RawFree(&interp->_initial_thread)` corrupts the heap; the process SIGSEGVs in the same free-threaded `new_threadstate` reservation path (`_PyIndexPool_AllocIndex`, `pystate.c:1671`) under OOM. Same underlying bug, recorded as `segfault`.
- **jit** (GIL-enabled debug): `n/a` -- the qsbr/tlbc reservation path does not exist (`Py_GIL_DISABLED` off); the reproducer raises `MemoryError` cleanly across the swept range.
- **upstream** (GIL-enabled, NDEBUG): `n/a` for this bug (same `Py_GIL_DISABLED`-off reason). It does segfault at a nearby `start`, but in an *unrelated* OOM site -- `make_unraisable_hook_args` -> `PyStructSequence_New` during `Py_EndInterpreter` finalization (`pylifecycle.c:2292`), not `free_threadstate`.

Six fuzzer vehicles (across `python-5` and `python-7`) all abort with the identical `_PyMem_DebugRawFree: bad ID` fatal whose C stack passes through `Py_NewInterpreterFromConfig`; each merely calls `concurrent.interpreters.create()` (or `_interpreters.create`) under the OOM sweep. (Other `python-7` `_PyMem_DebugRawFree` crashes that lack the `bad ID` sub-message are a different signature and are not counted here.)

## Versions

- main (3.16.0a0, commit 15d7406); aborts (`bad ID`) on the free-threaded debug+ASan build, segfaults on the free-threaded release build. JIT/upstream are GIL-enabled, so the affected `Py_GIL_DISABLED` path is absent (`n/a`).
