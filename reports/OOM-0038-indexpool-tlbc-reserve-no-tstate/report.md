# Fatal/segfault: `_PyIndexPool_AllocIndex` calls `PyErr_NoMemory()` with no active thread state while reserving a TLBC index during free-threaded sub-interpreter creation (`index_pool.c:167`)

_AI Disclaimer: this report was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

On free-threaded builds, creating a sub-interpreter under allocation failure can crash the
whole process while *reporting* the allocation failure. `new_interpreter()` deliberately
**detaches** the calling thread's thread state before building the new interpreter's first
thread state — so for that window there is no active thread state. In that window
`new_threadstate()` reserves a per-interpreter TLBC (thread-local bytecode) index via
`_Py_ReserveTLBCIndex()` → `_PyIndexPool_AllocIndex()`. For a fresh interpreter the index
pool is empty, so it grows with `PyMem_RawCalloc()`; under OOM that calloc fails and
`_PyIndexPool_AllocIndex()` calls `PyErr_NoMemory()`. But `PyErr_NoMemory()` →
`get_memory_error()` → `get_exc_state()` → `_PyInterpreterState_GET()`, which **requires an
active thread state**. There is none, so:

- **free-threaded DEBUG build:** `Fatal Python error: _PyInterpreterState_GET: the function
  must be called with an active thread state …` → `abort()`.
- **free-threaded RELEASE build:** the debug assertion is compiled out and the thread-local
  interpreter pointer is `NULL`, so `get_exc_state()` returns `&((PyInterpreterState*)0)->exc_state`
  and `MEMERRORS_LOCK(state)` dereferences a near-NULL address → **SIGSEGV**.

GIL-enabled builds are unaffected: the TLBC index pool is `Py_GIL_DISABLED`-only.

## Reproducer

```python
import _interpreters, _testcapi
_testcapi.set_nomemory(30, 0)        # fail every allocation from the 30th onward
_interpreters.create(reqrefs=True)   # build a sub-interpreter under OOM
```

Run free-threaded (`PYTHON_GIL=0`) on a build exposing `_testcapi.set_nomemory`. The exact
start index is sensitive to the allocation preamble (≈30–31 here), so the shipped `repro.py`
**self-sweeps** `set_nomemory(N, 0)` over a range in a fresh subprocess per `N` and stops at
the first `N` that triggers *this* bug — explicitly **skipping the adjacent OOM-0020** bad-free
(see below). Deterministic (8/8 at the trigger index) on debug-ft (`Fatal …_PyInterpreterState_GET`)
and release-ft (SIGSEGV). No windowing is required; a plain fail-forward sweep reaches it.
(Reduced from a `concurrent.interpreters` fuzzing vehicle, preserved as `vehicle_source.py`.)

## Backtrace

Free-threaded debug+ASan (commit `1b9fe5c`), `Fatal Python error: _PyInterpreterState_GET …`:

```
#13 get_memory_error          Objects/exceptions.c:4136   _PyInterpreterState_GET() via get_exc_state(), no tstate
#14 _PyErr_NoMemory           Objects/exceptions.c:4158   (gdb: tstate == 0x0)
#15 _PyIndexPool_AllocIndex   Python/index_pool.c:167     PyErr_NoMemory() after PyMem_RawCalloc() fails
#16 new_threadstate           Python/pystate.c:1671       _Py_ReserveTLBCIndex(interp)
#17 new_interpreter           Python/pylifecycle.c:2728   (thread detached at ~L2678)
#18 Py_NewInterpreterFromConfig Python/pylifecycle.c:2770
#19 _PyXI_NewInterpreter      Python/crossinterp.c:3269
#20 _interpreters_create_impl Modules/_interpretersmodule.c:878
```

gdb confirms the thread state is genuinely NULL (not stale):

```
#9  _PyErr_NoMemory (tstate=0x0) at Objects/exceptions.c:4158
#8  get_memory_error (allow_allocation=0) at Objects/exceptions.c:4136   -> _Py_FatalErrorFunc("_PyInterpreterState_GET", ...)
```

Free-threaded **release**+ASan, same chain, but the missing assertion turns it into a NULL
dereference (SEGV on `0x1500c` = `&((PyInterpreterState*)0)->exc_state.memerrors_lock`):

```
#0 _Py_atomic_compare_exchange_uint8  Include/cpython/pyatomic_gcc.h:105
#1 PyMutex_LockFlags                  Include/internal/pycore_lock.h:64
#2 get_memory_error                   Objects/exceptions.c:4113   MEMERRORS_LOCK(state), state = &interp->exc_state, interp == NULL
#3 _PyErr_NoMemory                    Objects/exceptions.c:4158
#4 _PyIndexPool_AllocIndex            Python/index_pool.c:167
#5 new_threadstate                    Python/pystate.c:1671
```

## Root cause

`new_interpreter()` (`Python/pylifecycle.c`) detaches the caller's thread state before
constructing the new interpreter's thread state, and explicitly forbids anything that needs a
running thread until `init_interp_create_gil()`:

```c
PyThreadState *save_tstate = _PyThreadState_GET();
...
/* From this point until the init_interp_create_gil() call, we must not do anything
   that requires that the GIL be held (or otherwise exist). */
if (save_tstate != NULL) {
    _PyThreadState_Detach(save_tstate);          /* ~L2678: no active thread state now */
}
...
tstate = _PyThreadState_New(interp, ...);        /* L2728 -> new_threadstate() */
```

On free-threaded builds `new_threadstate()` reserves a TLBC index:

```c
int32_t tlbc_idx = _Py_ReserveTLBCIndex(interp);     /* Python/pystate.c:1671 */
    -> _PyIndexPool_AllocIndex(&interp->tlbc_indices) /* Objects/codeobject.c:3303 */
```

and `_PyIndexPool_AllocIndex()` reports its own allocation failure with a Python exception:

```c
/* Python/index_pool.c */
if (heap_ensure_capacity(free_indices, pool->next_index + 1) < 0) {   /* PyMem_RawCalloc fails */
    UNLOCK_POOL(pool);
    PyErr_NoMemory();            /* L167: needs an active thread state — there is none here */
    return -1;
}
```

`PyErr_NoMemory()` calls `_PyErr_NoMemory(_PyThreadState_GET())` (the current tstate is NULL),
and `get_memory_error()` calls `get_exc_state()` → `_PyInterpreterState_GET()` to find the
per-interpreter MemoryError freelist/lock. With no active thread state the debug build's
`_Py_EnsureTstateNotNULL()` assertion fires (`Fatal Python error`), and the release build reads
a NULL interpreter pointer and segfaults in `MEMERRORS_LOCK`.

The sibling reservation on the very next lines, `_Py_qsbr_reserve()` (`pystate.c:1666`),
correctly returns `-1` **without** trying to raise. Only `_PyIndexPool_AllocIndex()` sets a
Python exception, and it is the one caller — `new_threadstate()` during interpreter bootstrap —
where doing so is illegal. The function's own comment even states it shifts failure handling
"to when indices are allocated, which happens at thread creation, where we are better equipped
to deal with failure" — but thread creation is exactly where there is no thread state to raise
on.

## Suggested fix

Make `_PyIndexPool_AllocIndex()` report failure by return value only, like its sibling
`_Py_qsbr_reserve()`:

```c
/* Python/index_pool.c */
if (heap_ensure_capacity(free_indices, pool->next_index + 1) < 0) {
    UNLOCK_POOL(pool);
    return -1;                   /* do NOT call PyErr_NoMemory() — caller has no tstate */
}
```

Its only caller, `new_threadstate()` (via `_Py_ReserveTLBCIndex()`), already turns a `-1` into
a clean `free_threadstate()` + `return NULL`, which `new_interpreter()` reports as
`_PyStatus_NO_MEMORY()` — the correct OOM-during-bootstrap outcome. (If a future caller of
`_Py_ReserveTLBCIndex()` does run with an active thread state and wants a Python exception, it
should raise it itself, after checking the return value.)

## Relationship to OOM-0020 (distinct bug, same function, adjacent allocation)

This is **not** OOM-0020, though both fire in `new_threadstate()` during sub-interpreter
creation under OOM:

| | OOM-0020 | this bug (OOM-0038) |
|---|---|---|
| failing reservation | `_Py_qsbr_reserve()` (pystate.c:1666) | `_Py_ReserveTLBCIndex()` (pystate.c:1671) |
| defect | cleanup `free_threadstate()` bad-frees the embedded `_initial_thread` | `_PyIndexPool_AllocIndex()` calls `PyErr_NoMemory()` with no thread state |
| signature | `_PyMem_DebugRawFree: bad ID` (debug) / heap-corruption SEGV (release) | `_PyInterpreterState_GET` fatal (debug) / NULL-deref SEGV (release) |
| fix | set `_initial_thread.base.interp` before publishing | `_PyIndexPool_AllocIndex()` returns `-1` without raising |

They sit on **adjacent allocation indices** of the same `create()` call. Empirically on
debug-ft-nojit-asan: `set_nomemory(29, 34)` → OOM-0020 (`bad ID`); `set_nomemory(30, 35)` →
this bug (`_PyInterpreterState_GET`), 8/8. Under a plain fail-forward sweep OOM-0020 fires one
index earlier and **masks** this one (its `_Py_qsbr_reserve` allocation comes first), which is
why OOM-0020's own reproducer only ever shows the bad-free. Fixing OOM-0020 alone would expose
this crash; fixing this alone would expose OOM-0020 on the TLBC path — they are independent
defects and need independent fixes.

## Notes

- Found by fusil OOM-injection fuzzing (`--oom-fuzz` / `--oom-seq`), vehicle module
  `concurrent.interpreters`. The crashing step is `create()` under the allocation sweep.
- Free-threading-specific: `_Py_ReserveTLBCIndex()`/`_PyIndexPool_AllocIndex()` and the
  `interp->tlbc_indices` pool are gated on `#ifdef Py_GIL_DISABLED`, so GIL-enabled builds never
  reach this path (n/a).
- Dedup keys deliberately use only the discriminating frames
  (`_PyIndexPool_AllocIndex@index_pool.c:167`, `_PyErr_NoMemory`/`get_memory_error@exceptions.c`,
  and the `_PyInterpreterState_GET` fatal message). The shared sub-interpreter-creation frames
  (`new_threadstate`, `new_interpreter`, `_PyXI_NewInterpreter`, `Py_NewInterpreterFromConfig`,
  `_interpreters_create_impl`) are kept here as context only — they collide with OOM-0020 and
  OOM-0037, which crash elsewhere on the same create path.

## Versions

- main (3.16.0a0, commit `1b9fe5c`). Reproduced (reduced `repro.py`) on debug-ft-nojit-asan and
  debug-ft-nojit (`Fatal Python error: _PyInterpreterState_GET`, SIGABRT) and release-ft-nojit /
  release-ft-nojit-asan (SIGSEGV, rc 139 / ASan SEGV). GIL builds: n/a (path is
  `Py_GIL_DISABLED`-only).

---

*Found with [fusil](https://github.com/devdanzin/fusil) OOM-injection fuzzing.*
