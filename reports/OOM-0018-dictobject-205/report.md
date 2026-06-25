# Abort: ownership assert in `set_keys` (`dictobject.c:205`)

*`PyObject_ClearManagedDict`'s OOM-recovery branch rewrites `ma_keys` via `set_keys(dict, Py_EMPTY_KEYS)` without first calling `ensure_shared_on_resize()`, so on free-threaded builds `set_keys`'s `_Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)` assert aborts when clearing a dict that's neither owned nor marked shared.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

On free-threaded builds, `PyObject_ClearManagedDict()` clears an object whose materialized dict still points at the object's inline values by calling `detach_dict_from_object()`, which `copy_values()`-copies the inline values out. Under OOM that copy fails and the function enters a recovery branch that rewrites `dict->ma_keys` via `set_keys(dict, Py_EMPTY_KEYS)` (`Objects/dictobject.c:7896`). Unlike every other path that rewrites `ma_keys`, this branch never calls `ensure_shared_on_resize()`, so `set_keys`'s debug assert `_Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)` (`dictobject.c:205`) fires whenever the dict being cleared is neither owned by the current thread nor already marked shared — and the interpreter aborts.

Two routes reach this unguarded `set_keys`, both observed: the **cyclic GC clearing such an object under OOM** (`delete_garbage -> subtype_clear -> PyObject_ClearManagedDict`), which is the **deterministic** manifestation the reproducer and the vehicles actually take (8/8 on a normal run); and a **cross-thread dealloc** where biased reference counting routes the last decref through `_Py_brc_queue_object` on a non-owning thread (a rarer race, captured only intermittently under gdb). Both converge on the same defect, and the fix is the same.

## Reproducer

**Minimal reproducer** (`repro_minimal.py`, stdlib-only, no `unittest.mock`; deterministic,
10/10 on `ft_debug_asan` @`1b9fe5c`; requires a free-threaded debug build, `PYTHON_GIL=0`):

```python
from _testcapi import set_nomemory
class C: pass
o = C()
o.self = o          # inline value + self-cycle: survives to the shutdown cyclic GC
o.__dict__          # MATERIALIZE the managed dict (ma_values -> inline values)
set_nomemory(1)     # armed at shutdown: detach_dict_from_object fails -> set_keys recovery -> assert
```

A trivial heap-type instance has a managed `__dict__`; putting it in a self-cycle
(`o.self = o`) keeps it alive into interpreter shutdown, and accessing `o.__dict__`
**materializes** that dict so its `ma_values` still points at the inline values — the
precondition for the buggy branch. A bare, unmaterialized instance has
`_PyObject_GetManagedDict() == NULL` and takes the harmless early return: removing the
`o.__dict__` line makes the crash disappear (verified 0/8). With allocation failure armed,
the shutdown cyclic GC clears it via `delete_garbage -> subtype_clear ->
PyObject_ClearManagedDict`, whose OOM-recovery branch trips the assert. Because the crash is
in the **shutdown GC it cannot be swept**; a fixed `set_nomemory(1)` is used (the failing
`detach_dict_from_object` allocation is ~the second allocation during shutdown for this
minimal object — much earlier than the `MagicMock` vehicle's `N≈200` window, which did far
more setup).

**Published path** (`repro.py`, shrinkray-reduced from the `wsgiref.util` vehicle; 30/30; the
form in the gist) — same shutdown-GC route via a `MagicMock` (managed `__dict__`) abandoned
into a traceback cycle:

```python
from unittest.mock import MagicMock
from _testcapi import set_nomemory

set_nomemory(200)              # fail allocations from the 200th onward (lands in shutdown GC)
(MagicMock(), undefined_name)  # build a MagicMock (managed __dict__), then NameError abandons
                               # it into a traceback cycle -> survives to shutdown GC
```

Here the `set_nomemory(N)` argument must land the failing allocation inside the shutdown GC:
the working window is roughly `N` in `[113, 900]` on this build (`N=200` is comfortably
central) — too small fails during setup, too large (e.g. `999`) overshoots shutdown. The
window is an allocation-count effect, **not** tied to the small-int cache (tested `N=254..258`
straddling the 256 boundary: no change). Minimization **complete**; the full fuzzer vehicle
is preserved as `vehicle_source.py`.

## Backtrace

Deterministic path (reproducer + vehicles, `bt` under gdb):

```
#8  set_keys                  Objects/dictobject.c:205          <- assert _Py_IsOwnedByCurrentThread(mp) || IS_DICT_SHARED(mp)
#9  PyObject_ClearManagedDict Objects/dictobject.c:7896         <- set_keys(dict, Py_EMPTY_KEYS) in the OOM-recovery branch
#10 subtype_clear             Objects/typeobject.c:2700
#11 delete_garbage            Python/gc_free_threading.c:1761
#12 gc_collect_internal       Python/gc_free_threading.c:2176
#13 gc_collect_main           Python/gc_free_threading.c:2257   <- reason=_Py_GC_REASON_SHUTDOWN
#14 finalize_modules          Python/pylifecycle.c:1955
#15 _Py_Finalize              Python/pylifecycle.c:2491
```

Alternate path (cross-thread dealloc) — same assert/branch, reached via biased reference
counting. Captured during first triage but **did not recur in a 210-run local census** (see
Notes); likely host-specific timing:

```
#10 subtype_dealloc           Objects/typeobject.c:2847
#11 _Py_Dealloc               Objects/object.c:3319
#12 _Py_brc_queue_object      Python/brc.c:91                   <- object owned by another thread, freed here
#13 Py_DECREF                 ./Include/refcount.h:363          <- cross-thread last decref
```

## Root cause

`Objects/dictobject.c`, `PyObject_ClearManagedDict()` (L7865), the `detach_dict_from_object()`-failed branch:

```c
    Py_BEGIN_CRITICAL_SECTION(dict);
    err = detach_dict_from_object(dict, obj);   /* L7885: copy_values() fails under OOM -> -1 */
    Py_END_CRITICAL_SECTION();
    if (err) {
        assert(PyErr_Occurred() == PyExc_MemoryError);
        PyErr_FormatUnraisable(...);
        Py_BEGIN_CRITICAL_SECTION(dict);
        PyDictKeysObject *oldkeys = dict->ma_keys;
        set_keys(dict, Py_EMPTY_KEYS);                  /* L7896: rewrites ma_keys WITHOUT marking shared */
        dict->ma_values = NULL;
        dictkeys_decref(oldkeys, IS_DICT_SHARED(dict)); /* L7898: same wrong shared flag */
        STORE_USED(dict, 0);
        clear_inline_values(_PyObject_InlineValues(obj));
        Py_END_CRITICAL_SECTION();
    }
```

`set_keys()` (L202) asserts `_Py_IsOwnedByCurrentThread((PyObject *)mp) || IS_DICT_SHARED(mp)` (L205). Every other site that rewrites `ma_keys` -- `dictresize` (L2167), `clear` (L3098), update (L4144) -- first calls `ensure_shared_on_resize(mp)` (L1418), which marks a dict that isn't owned by the current thread as `DICT_SHARED`. This recovery branch, added in commit `6c450f44c283`, skips that step. Because the object is freed via biased reference counting on a thread other than its owner, `_Py_IsOwnedByCurrentThread(dict)` is false and the dict was never marked shared, so the invariant is violated. It is a missing "mark shared before resize", not a use-after-free.

## Suggested fix

Mark the dict shared before rewriting `ma_keys`, mirroring the normal resize paths. Inside the recovery critical section, just before `set_keys`:

```c
    Py_BEGIN_CRITICAL_SECTION(dict);
    PyDictKeysObject *oldkeys = dict->ma_keys;
    ensure_shared_on_resize(dict);     /* <-- add: marks DICT_SHARED if not owned by current thread */
    set_keys(dict, Py_EMPTY_KEYS);
    dict->ma_values = NULL;
    dictkeys_decref(oldkeys, IS_DICT_SHARED(dict));   /* now sees the correct shared flag */
    ...
```

This also corrects the `IS_DICT_SHARED(dict)` argument to `dictkeys_decref` (L7898), so the old keys are freed with the proper QSBR delay protecting concurrent lock-free readers.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). Free-threading-specific: `set_keys`'s ownership assert and the `_Py_IsOwnedByCurrentThread`/`IS_DICT_SHARED` machinery only exist under `Py_GIL_DISABLED` (the non-FT `set_keys` at L270 is a bare `mp->ma_keys = keys`). Reproduces as an **abort only on the FT debug build** -- the FT release build defines `NDEBUG`, so the assert is compiled out, but the same branch then rewrites `ma_keys` and decrefs the old keys with the wrong `IS_DICT_SHARED()` value, skipping the QSBR delay (a latent memory-safety hazard for concurrent readers, not just a debug assert). GIL builds (`jit`, `upstream`) lack the field and the assert entirely and run the reproducer cleanly. Per the OOM-catalog convention for assert-based aborts, non-debug builds are recorded as `n/a`.

Minimization **complete** (2026-06-19): the deterministic manifestation is the cyclic GC
clearing a managed-dict object under OOM, *not* a cross-thread race. A crash-face census of
the `wsgiref_util` vehicle resolved the caller frame above `PyObject_ClearManagedDict` (via
`addr2line`) on every run: **shutdown-GC (`subtype_clear`) in 160/160 runs without gdb and
50/50 under gdb — 0/210 cross-thread**. The original "racy / ~1-in-20 / cross-thread"
characterization (and the `_Py_brc_queue_object` backtrace below) was a real capture during
first triage but **does not recur on this local build**; it is host-specific timing (the
fuzzing host runs the older pre-`ad1513a263b` build, cf. `host_only_candidates.md`). gdb does
**not** perturb the face here — both modes land on shutdown-GC. shrinkray reduced the vehicle
to the 30/30 4-line repro above; the `MagicMock()`-abandoned-into-a-traceback-cycle that all
three vehicles (`wsgiref_util`, `pickletools`, `sched`) build is exactly what survives to
shutdown GC. The `set_nomemory` argument selects when the allocation fails (window `[113, 900]`
on this build); it is not tied to the small-int cache.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build. Release/JIT/upstream builds: assertion compiled out / not present (`n/a`). Recovery branch introduced in commit `6c450f44c283`.

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
