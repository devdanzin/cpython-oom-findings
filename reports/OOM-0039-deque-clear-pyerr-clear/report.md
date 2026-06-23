# Fatal: `deque_clear` clears the in-flight exception via its `newblock`-failure `PyErr_Clear()` (`_collectionsmodule.c:751`)

*Under OOM a `collections.deque` is freed with a `MemoryError` in flight; `deque_dealloc` → `deque_clear` tries to allocate a fresh block to drain the deque safely, that allocation also fails, and the fallback does `PyErr_Clear()` — clobbering the caller's pending exception and tripping the gh-89373 `_Py_Dealloc` debug invariant.*

_AI Disclaimer: this report was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Under memory pressure a `collections.deque` can be deallocated while an exception (a `MemoryError` raised mid-operation) is in flight — e.g. its last reference is dropped while a frame unwinds, or a half-built deque is torn down after its `__init__` failed under OOM. `deque_dealloc()` calls `deque_clear()` to drop the items. To empty the deque safely (decref'ing items can re-enter and mutate the deque), `deque_clear` first allocates a *fresh empty block* via `newblock()`. **In the unlikely event memory is full**, `newblock()` fails and `deque_clear` does `PyErr_Clear(); goto alternate_method;`.

When `deque_clear` runs from `deque_dealloc` with a `MemoryError` already in flight **and the heap is still exhausted** (so `newblock()` also fails), that `PyErr_Clear()` wipes the *caller's* pending exception. A `tp_dealloc` must leave `tstate->current_exception` unchanged (gh-89373); this one does not. The result is `Fatal Python error: _Py_Dealloc: Deallocator of type 'collections.deque' cleared the current exception`. Fatal on debug builds only (the invariant is `Py_DEBUG`-gated); on release builds the same defect is a silent corruption of the error indicator — a `MemoryError` raised at the deque's last decref is silently swallowed.

This is the same *symptom* family as OOM-0007 / OOM-0023 (a `tp_dealloc` clears the in-flight exception), but a **distinct C site and fix**. It is the OOM-0007 shape — a *type-specific* deallocator (`deque_clear`/`deque_dealloc` in `Modules/_collectionsmodule.c`), **not** OOM-0023's generic `subtype_dealloc`. OOM-0023's `subtype_dealloc` bracket does **not** cover it: a bare deque that is never an attribute of a managed-dict instance reproduces this fatal without `subtype_dealloc` on the stack.

## Reproducer

Minimal, stdlib-only, deterministic via the `set_nomemory` sweep. A non-empty `deque` is deallocated with a `MemoryError` in flight while the heap is still exhausted.

```python
import faulthandler; faulthandler.enable()
from collections import deque
from _testcapi import set_nomemory

DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)            # install the hook disarmed (avoid re-swapping the allocator)

def drop_a_deque():
    d = deque(range(64))            # non-empty -> deque_clear takes the newblock() path
    return None                     # d hits its last ref here; if a MemoryError is in flight
                                    # AND newblock() still fails -> PyErr_Clear() clobbers it

for start in range(2000):
    set_nomemory(start, start + 4)  # fail allocations [start, start+4), then resume
    try:
        try:
            drop_a_deque()
        finally:
            set_nomemory(DISABLE, 0)
    except MemoryError:
        pass
print("survived (no crash)")
```

Crashes on the FT debug+ASan build with `Fatal Python error: _Py_Dealloc: Deallocator of type 'collections.deque' cleared the current exception`.

**Why the windowed `set_nomemory(start, start+k)` matters.** The crash requires the allocation failure to *persist into* the dealloc, so `newblock()` inside `deque_clear` fails. A window that fails only one allocation (`k=1`) does **not** reproduce: the `MemoryError` is raised, but by the time the deque is torn down the window has closed, `newblock()` succeeds, and `deque_clear` never reaches `PyErr_Clear()`. `k=0` (fail-forever, the legacy single-call semantics) and `k>=2` both reproduce. This windowed `set_nomemory` is fusil's `--oom-seq` mode.

The full fuzzer vehicle (the original crash: `_pyrepl.pager.pipe_pager` under `--oom-seq`, where the deque is an attribute of a managed-dict instance torn down via `subtype_dealloc` → `PyObject_ClearManagedDict`) is preserved as `vehicle_source.py`.

## Backtrace

```
Fatal Python error: _Py_Dealloc: Deallocator of type 'collections.deque' cleared the current exception
Stack (most recent call first):
  File ".../repro.py", line 17 in drop_a_deque

# C path (gdb, break on _collectionsmodule.c:751 = the PyErr_Clear, reached only when newblock() fails):
#0 deque_clear        Modules/_collectionsmodule.c:751   PyErr_Clear();  (newblock() returned NULL)
#1 deque_dealloc      Modules/_collectionsmodule.c:1556  (void)deque_clear(self)
#2 _Py_Dealloc        Objects/object.c:3319              op == the deque; old_exc == the in-flight MemoryError
#3 Py_DECREF          Include/refcount.h:359
#4 type_call          Objects/typeobject.c:2487          decref of the half-built deque (its __init__ failed under OOM)
#5 _PyObject_MakeTpCall Objects/call.c:242
```

`old_exc` (saved by the enclosing `_Py_Dealloc` at frame #2) = the pending `MemoryError`; after `deque_dealloc` returns, `tstate->current_exception` = `NULL` → the `_Py_Dealloc` check at `object.c:3338` fatals with "cleared the current exception". See `backtrace.txt` for the authoritative ASan capture and the gdb chain.

## Root cause

`Modules/_collectionsmodule.c`, `deque_clear` (L722), the block-preallocation fast path (L749-752):

```c
    b = newblock(deque);
    if (b == NULL) {
        PyErr_Clear();          /* L751 */
        goto alternate_method;
    }
```

`newblock()` (L177-189) calls `PyMem_Malloc`; on failure it does `PyErr_NoMemory()` and returns `NULL`. So under OOM, inside `deque_clear`: `newblock()` sets a fresh `MemoryError` (overriding the in-flight one), then `PyErr_Clear()` clears it outright. `deque_clear` is reached two ways:

- as `tp_clear` (GC) — there is normally no exception in flight, so the `PyErr_Clear()` is harmless; and
- from `deque_dealloc` (L1556, `(void)deque_clear(self)`) — **here a caller's exception can be in flight**, and clearing it violates gh-89373.

Nowhere in the `deque_dealloc` path is the pending exception saved/restored. (The deque in the reproducer has no weakrefs, so `FT_CLEAR_WEAKREFS` is a no-op; `deque_clear`'s `PyErr_Clear()` is the only error-indicator-touching code in the teardown — confirmed by the gdb breakpoint at L751 firing immediately before the fatal. The other potentially-clearing path, `PyObject_ClearWeakRefs`, is already protected: it brackets weakref callbacks with `PyErr_GetRaisedException`/`PyErr_SetRaisedException` — `Objects/weakrefobject.c:1053/1095`.)

The `PyErr_Clear()` is **exception-type-agnostic**: it clears whatever `tstate->current_exception` holds, so *any* in-flight exception — not just `MemoryError` — is lost when a non-empty deque is freed while it is pending and `newblock()` fails. `MemoryError` is merely the common victim, because the same exhaustion that makes `newblock()` fail is usually what is propagating. The fatal message names the deallocated object's type (`collections.deque`), never the cleared exception's type.

This fallback (preallocate an empty block; on failure `PyErr_Clear()` + drain via the slow `alternate_method`) was introduced in [bpo-25135](https://bugs.python.org/issue25135) (2015, Python 2.7/3.5/3.6); that discussion covered the re-entrancy and allocation concerns but never the exception-state hazard during deallocation. The `PyErr_Clear()` is legitimate for `deque_clear`'s *other* callers — `tp_clear` (GC), the `.clear()` method, re-`__init__` — where no caller exception is in flight; it is only wrong on the `deque_dealloc` path, which is why the fix belongs in `deque_dealloc` (save/restore around `deque_clear`) rather than in removing the `PyErr_Clear()`.

## Suggested fix

Don't let `deque_clear`'s allocation-failure fallback disturb a pre-existing exception. Either preserve/restore around the `deque_clear` call in `deque_dealloc` (the `slot_tp_finalize` / `context_tp_dealloc`-fix pattern):

```c
static void
deque_dealloc(PyObject *self)
{
    dequeobject *deque = dequeobject_CAST(self);
    PyTypeObject *tp = Py_TYPE(deque);
    Py_ssize_t i;

    PyObject_GC_UnTrack(deque);
    FT_CLEAR_WEAKREFS(self, deque->weakreflist);

    PyObject *exc = PyErr_GetRaisedException();   /* preserve in-flight exception */
    if (deque->leftblock != NULL) {
        (void)deque_clear(self);
        assert(deque->leftblock != NULL);
        freeblock(deque, deque->leftblock);
    }
    PyErr_SetRaisedException(exc);                 /* restore before returning */

    deque->leftblock = NULL;
    /* ... */
}
```

or, more locally, have `deque_clear` save/restore around the `newblock`-failure path instead of a bare `PyErr_Clear()` (so the only exception it touches is the `MemoryError` `newblock()` itself raised, never a pre-existing one). The `deque_dealloc` bracket is preferable: it also covers any other arbitrary teardown (item decrefs) that could disturb the exception, matching how `context_tp_dealloc` should be fixed for OOM-0007.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`), fusil `--oom-seq` mode. Original vehicle: `fusil_fleet_oom_oca/session-3914`, `_pyrepl.pager.pipe_pager` → `subprocess._posix_spawn` raising `MemoryError`, with the deque held as an attribute of a fusil "weird" instance and torn down via `subtype_dealloc` → `PyObject_ClearManagedDict` → `clear_inline_values`. Three independent decref paths all reach the same `deque_clear` defect: (1) that `subtype_dealloc` managed-dict teardown; (2) a bare deque frame local on unwind (`_PyFrame_ClearLocals` → `PyStackRef_XCLOSE`); (3) a half-built deque whose `__init__` failed under OOM (`type_call:2487`, used by the minimal repro).

**Distinct from OOM-0007 and OOM-0023.** Same `Deallocator of type 'X' cleared the current exception` symptom, but OOM-0007 is `context_tp_dealloc` (`Python/context.c`) and OOM-0023 is the generic `subtype_dealloc` (`Objects/typeobject.c`); this is `deque_clear`/`deque_dealloc` (`Modules/_collectionsmodule.c`). OOM-0023's `subtype_dealloc` fix does not cover it (the bare-deque path never touches `subtype_dealloc`).

**Debug-only signature.** The `_Py_Dealloc` invariant is `#ifdef Py_DEBUG`, so it fatals on the `Py_DEBUG` builds (`ft_debug_asan`, `jit`) — identical message on both — and is compiled out on release (`ft_release`, `upstream`), where the minimal repro exits cleanly (the `MemoryError` is silently dropped). Recorded `n/a` for the release builds.

**Reachable without `--oom-fuzz`.** The trigger is a genuine `newblock()` allocation failure, which occurs under any real memory pressure — not only `set_nomemory` injection. In particular fusil caps each child's address space (`RLIMIT_AS`) at its default `process_max_memory` (2 GB) on a *normal* run: a fuzzed program approaching the cap gets real `NULL` from `PyMem_Malloc`, and if a non-empty deque is torn down while an ordinary fuzzer-induced exception (`TypeError`, `ValueError`, `KeyboardInterrupt`, …) is propagating, the same fatal fires with that exception silently cleared. This is consistent with deque-dealloc clears-exc crashes observed in plain (non-OOM) fuzzing runs. On a real production debug build the same holds for any genuine OOM.

**Prior art / precedent.** Not present in the CPython issue tracker as of 2026-06-23 (no report of a deque dealloc clearing the in-flight exception). The same bug *class* — an unconditional `PyErr_Clear()` or teardown swallowing a pending exception, fixed by save/restore — has been handled elsewhere: [python/cpython#131173](https://github.com/python/cpython/issues/131173) (`take_ownership` clears `MemoryError`), [#145966](https://github.com/python/cpython/issues/145966) (`_csv` `DIALECT_GETATTR` masks non-`AttributeError`), [bpo-33713](https://bugs.python.org/issue33713) (memoryview sets an exception in `tp_clear`).

## Versions

- main (3.16.0a0). Reproduced (fatal) deterministically on the free-threaded debug+ASan build, commit `1b9fe5c` (Clang 21), and on the JIT debug build. Originally found on the `oca` box's GCC 13.3.0 build, commit `27148d0857e` — so the defect is neither compiler- nor revision-specific. Release builds: invariant compiled out (`n/a`; clean exit).

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking OOM-related crash findings.*
