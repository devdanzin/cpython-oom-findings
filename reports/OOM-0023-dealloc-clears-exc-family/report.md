# Title

Fatal: `_Py_Dealloc: Deallocator of type 'X' cleared the current exception` for ordinary stdlib instances (`_StoreAction`, `UnknownHandler`/`ProxyHandler`, `LogRecord`) — generic `subtype_dealloc` (`Objects/typeobject.c`) does not preserve the pending exception under OOM

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

A whole family of fatals shares one signature: `Deallocator of type 'X' cleared the current exception`, where `X` is a plain Python class defined in the standard library — `argparse._StoreAction`, `urllib.request.UnknownHandler` / `ProxyHandler`, `logging.LogRecord`. Under memory pressure one of these instances is deallocated while a `MemoryError` is in flight (its last reference is dropped while a frame unwinds). Because none of these classes defines `__del__`, their `tp_dealloc` is the generic `subtype_dealloc` and `tp_finalize` is `NULL`, so the exception-preserving finalize path is skipped. `subtype_dealloc` then clears the instance slots and decrefs the instance `__dict__` — arbitrary teardown that decrefs the attribute values — **without saving/restoring `tstate->current_exception`**. That teardown clears the pending exception, tripping the gh-89373 debug invariant in `_Py_Dealloc` and aborting. Fatal on debug builds only (the invariant is `Py_DEBUG`-gated); on release builds the same defect is a silent corruption of the error indicator.

This is **one generic root cause** for the whole non-`Context` family (distinct from OOM-0007, which is the *type-specific* `context_tp_dealloc` in `Python/context.c`). The common site here is `subtype_dealloc` in `Objects/typeobject.c`, which every pure-Python heap type without `__del__` inherits.

## Reproducer

Stdlib-only, deterministic on the FT debug+ASan build (crashes around `start=276` within the sweep). `http.server._main` builds an `argparse` parser; under the OOM sweep an allocation fails mid-construction and a half-built `_StoreAction` (held on the unwinding frame) is deallocated with the `MemoryError` in flight. The single up-front warm call is required so the OOM lands inside parser construction rather than during the lazy imports `_main` triggers (which would hit the unrelated import-time abort, OOM-0003).

```python
import http.server
from _testcapi import set_nomemory, remove_mem_hooks
import faulthandler
faulthandler.enable()

# Warm all lazy imports (argparse, gettext, re) so OOM lands in _main's
# parser construction, not in module import.
try:
    http.server._main(['--help'])
except SystemExit:
    pass

for start in range(1000):
    set_nomemory(start, 0)
    try:
        try:
            http.server._main([])          # _StoreAction torn down mid-unwind under MemoryError
        finally:
            remove_mem_hooks()
    except (SystemExit, MemoryError):
        pass
    except BaseException:
        pass
```

Crashes on the FT debug+ASan build with `Fatal Python error: _Py_Dealloc: Deallocator of type '_StoreAction' cleared the current exception`. A single fixed `set_nomemory(276, 0)` does **not** reproduce — the exact allocation index depends on the swept state, so the sweep form is the reliable trigger.

## Backtrace

```
Fatal Python error: _Py_Dealloc: Deallocator of type '_StoreAction' cleared the current exception
Stack (most recent call first):
  File ".../Lib/http/server.py", line 1091 in _main   (parser.add_argument cascade)

# C path (gdb):
#8  _Py_Dealloc          Objects/object.c:3338   err="...cleared the current exception", tp_name=="_StoreAction"
#10 PyStackRef_XCLOSE    Include/internal/pycore_stackref.h:726
#11 _PyFrame_ClearLocals Python/frame.c:101       frame unwinding under pending MemoryError
#12 _PyFrame_ClearExceptCode Python/frame.c:126
#13 clear_thread_frame   Python/ceval.c:1954
#14 _PyEval_EvalFrameDefault
```

`old_exc` (saved by `_Py_Dealloc`) = the pending `MemoryError`; `tstate->current_exception` = `NULL` after the instance `tp_dealloc` runs (`subtype_dealloc`) → "cleared". The deallocated object is a pure-Python instance (no `__del__`).

## Root cause

`Objects/typeobject.c`, `subtype_dealloc` (L2719). For a GC heap type whose nearest non-`subtype_dealloc` base differs, after the (skipped, because `tp_finalize == NULL`) finalize step it clears slots and the instance dict:

```c
    /* Clear slots up to the nearest base with a different tp_dealloc */
    base = type;
    while ((basedealloc = base->tp_dealloc) == subtype_dealloc) {
        if (Py_SIZE(base))
            clear_slots(base, self);          /* L2840: decrefs slot values */
        base = base->tp_base;
    }

    /* If we added a dict, DECREF it ... */
    if (type->tp_flags & Py_TPFLAGS_MANAGED_DICT) {
        PyObject_ClearManagedDict(self);      /* L2847: decrefs every attribute value */
    }
    else if (type->tp_dictoffset && !base->tp_dictoffset) {
        ...
        Py_DECREF(dict);                      /* L2854 */
    }
```

`clear_slots`, `PyObject_ClearManagedDict`, and `Py_DECREF(dict)` run arbitrary decref cascades over the instance's attribute values, any of which can clear or normalize `tstate->current_exception`. **Nowhere in `subtype_dealloc` is the pending exception saved/restored.** The only exception-preserving wrapper is in the `__del__` path: `slot_tp_finalize` (L11209) brackets the call with `_PyErr_GetRaisedException` / `_PyErr_SetRaisedException` (L11213, L11235). Because `_StoreAction`, `UnknownHandler`, `ProxyHandler`, and `LogRecord` have no `__del__`, `tp_finalize` is `NULL`, that wrapper is never invoked, and the dict/slot teardown happens unprotected. A `tp_dealloc` must leave `tstate->current_exception` unchanged (gh-89373); `subtype_dealloc` does not when it runs with an exception in flight.

This is build-agnostic memory-state corruption; the OOM fuzzer merely makes it reachable by reliably putting a `MemoryError` in flight at the exact moment one of these objects hits its last decref during frame unwinding.

## Suggested fix

Bracket the destructive part of `subtype_dealloc` (slot/dict teardown and the base `tp_dealloc` call) with exception save/restore, the same pattern already used in `slot_tp_finalize`:

```c
    PyThreadState *tstate = _PyThreadState_GET();
    PyObject *exc = _PyErr_GetRaisedException(tstate);   /* preserve in-flight exception */

    /* ... clear_slots / PyObject_ClearManagedDict / Py_DECREF(dict) ... */
    /* ... basedealloc(self); ... */

    _PyErr_SetRaisedException(tstate, exc);              /* restore before returning */
```

(`exc` must be saved/restored without referencing `self` after `basedealloc(self)`.) This single change covers the entire non-`Context` family, since all affected types inherit `subtype_dealloc`. The narrower per-type alternative — preserving the exception in each affected stdlib `tp_dealloc` — is not applicable here because these are pure-Python classes with no custom deallocator; the fix must live in the generic path.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). **One root, many vehicles.** Nine fuzzer vehicles across four stdlib types all emit the identical `cleared the current exception` fatal: `_StoreAction` (argparse, via `http.server._main`), `UnknownHandler` / `ProxyHandler` (urllib.request, xml.sax.saxutils), `LogRecord` (logging, via concurrent.futures.process). All four are ordinary `object` subclasses with no `__del__`, so they share the single `subtype_dealloc` defect — this report covers the family as one bug, not per-type.

Relationship to OOM-0007 (`Context`): **same _symptom and same class of defect_ (a `tp_dealloc` clears the in-flight exception), but a different C site and fix location.** OOM-0007 is the dedicated `context_tp_dealloc` in `Python/context.c`; this family is the generic `subtype_dealloc` in `Objects/typeobject.c`. They are best fixed independently (Context has its own C deallocator that needs its own bracket), which is why `Context` is excluded from this cluster.

**Debug-only signature.** The `_Py_Dealloc` invariant is `#ifdef Py_DEBUG`. On the FT debug+ASan build it fatals deterministically with this message. The JIT build is also `Py_DEBUG=1`, but on this vehicle the OOM race lands at an earlier, unrelated site (`re._compiler._optimize_charset`) and segfaults *before* reaching the `_StoreAction` teardown, so it does not surface this signature (note: unlike OOM-0007, where JIT did fatal with the Context signature). On release builds (ft_release, upstream; `Py_DEBUG=0`) the invariant is compiled out and the same vehicle segfaults at an unrelated downstream OOM site. Hence ft_release/jit/upstream are recorded as `n/a` / segv for this signature.

## Versions

- main (3.16.0a0), commit 15d7406. Reproduces (fatal) deterministically on the free-threaded debug+ASan build via the sweep above. Release/upstream: invariant compiled out (`n/a`; segfault elsewhere). JIT (debug): does not reach this signature on the vehicle (segfaults earlier under OOM).
