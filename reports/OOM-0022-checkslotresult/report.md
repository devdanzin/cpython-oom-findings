# Title

Fatal: `_Py_CheckSlotResult`: "Slot __delitem__ of type dict succeeded with an exception set" in `reload_singlephase_extension` (`Python/import.c`) when `_modules_by_index_set()` fails under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Re-importing a single-phase (legacy) C extension module routes through `reload_singlephase_extension()`. After the module is rebuilt it calls `_modules_by_index_set()` (`Python/import.c:2010`) to record it in the per-interpreter `modules_by_index` list. Under OOM that call fails (its internal `PyList_New`/`PyList_Append` raises `MemoryError` and returns -1). The error-cleanup branch then runs `PyMapping_DelItem(modules, info->name)` (`import.c:2011`) **with the `MemoryError` still set**. The delete from `sys.modules` (a dict) *succeeds*, so the debug check `assert(_Py_CheckSlotResult(o, "__delitem__", res >= 0))` (`Objects/abstract.c:280`) sees `success && PyErr_Occurred()` and aborts the interpreter via `_Py_FatalErrorFormat`.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle, then cleaned; deterministic on the
`ft_debug_asan` build, re-verified 10/10). A dict `__delitem__` slot succeeds with an
exception set under OOM. (This minimal repro is `ft_debug_asan`-specific; the build matrix
below is verified against the full `vehicle_source.py`, which also fatals on the `jit` debug
build via the readline single-phase-extension reload path the minimal form doesn't exercise.)

```python
import faulthandler, pdb
faulthandler.enable()
from _testcapi import set_nomemory
for start in range(1000):
    set_nomemory(start)
    try:
        pdb.runcall()
    except BaseException:
        pass
print("done, no crash")
```

The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
#8  _Py_CheckSlotResult          Objects/call.c:80      <- "Slot __delitem__ ... succeeded with an exception set"
#9  PyObject_DelItem             Objects/abstract.c:280 <- assert(_Py_CheckSlotResult(o,"__delitem__",res>=0))
#10 reload_singlephase_extension Python/import.c:2011   <- PyMapping_DelItem(modules, info->name) cleanup
#11 import_find_extension        Python/import.c:2043
#12 _imp_create_dynamic_impl     Python/import.c:5468
```

The faulting object is the live `sys.modules` dict and the delete *succeeds*
(`res == 0`); the pending object is a `MemoryError` (refcount 1) left set by the
failed `_modules_by_index_set()` at `import.c:2010`. This is a stale-exception /
missing-error-clear bug, not a NULL/freed pointer.

## Root cause

`Python/import.c`, `reload_singlephase_extension()` (L2009-2014):

```c
    Py_ssize_t index = _get_cached_module_index(cached);
    if (_modules_by_index_set(tstate->interp, index, mod) < 0) {   /* L2010: raises MemoryError under OOM */
        PyMapping_DelItem(modules, info->name);                    /* L2011: runs with MemoryError still set */
        Py_DECREF(mod);
        return NULL;
    }
```

`_modules_by_index_set()` (L577) can fail by raising `MemoryError`:

```c
    if (MODULES_BY_INDEX(interp) == NULL) {
        MODULES_BY_INDEX(interp) = PyList_New(0);          /* alloc -> can fail */
        ...
    }
    while (PyList_GET_SIZE(MODULES_BY_INDEX(interp)) <= index) {
        if (PyList_Append(MODULES_BY_INDEX(interp), Py_None) < 0) {   /* alloc -> can fail */
            return -1;
        }
    }
```

When it returns -1 with `MemoryError` set, the cleanup calls
`PyMapping_DelItem(modules, info->name)` -> `PyObject_DelItem` ->
`dict_ass_subscript` (`sys.modules` is a dict). The key is present, so the slot
*succeeds* (`res == 0`). On a debug build, `PyObject_DelItem`
(`Objects/abstract.c:280`) wraps the call in
`assert(_Py_CheckSlotResult(o, "__delitem__", res >= 0))`, and
`_Py_CheckSlotResult` (`Objects/call.c:86-90`) treats "slot succeeded while an
exception is set" as a fatal interpreter invariant violation, calling
`_Py_FatalErrorFormat`. The defect is that the cleanup path performs an operation
that runs the dict `__delitem__` slot without first preserving/clearing the
already-pending exception.

## Suggested fix

Preserve and restore the pending exception around the cleanup deletion (the
established CPython idiom for "best-effort cleanup with an error already set"):

```c
    if (_modules_by_index_set(tstate->interp, index, mod) < 0) {
        PyObject *exc = PyErr_GetRaisedException();   /* save the MemoryError */
        PyMapping_DelItem(modules, info->name);       /* slot now runs with no exc set */
        PyErr_SetRaisedException(exc);                /* restore it */
        Py_DECREF(mod);
        return NULL;
    }
```

Equivalently, wrap the delete in `_PyErr_StashExceptionInUnraisable`-style
save/restore, or only delete when no exception is pending. The same stale-exception
hazard applies to any cleanup that invokes object slots after an allocation failure.

## Notes

Found by OOM-injection fuzzing (`_testcapi.set_nomemory`). The fatal check is a
debug-only invariant: `_Py_CheckSlotResult` at `Objects/abstract.c:280` is invoked
inside `assert(...)`, compiled out under `-DNDEBUG`. Build matrix on this crasher's
`source.py`:

- **ft_debug_asan** (Py_DEBUG=1, FT): aborts, `_Py_CheckSlotResult` fatal (rc 134). *Authoritative.*
- **jit** (Py_DEBUG=1, GIL): same `_Py_CheckSlotResult` fatal abort (rc 134) -- assert compiled in.
- **ft_release** (NDEBUG, FT): runs cleanly (rc 0) -- assert compiled out; the stale
  `MemoryError` is later overwritten/cleared with no observable effect at this site.
- **upstream** (NDEBUG, GIL): does **not** hit this site; segfaults elsewhere under the
  same OOM pressure (faulthandler stack at `pdb._pyrepl_available` -> `_find_and_load`
  import-lock path), a *separate* OOM-robustness bug. Recorded `n/a` for this finding.

Two fuzzer vehicles reach the identical fatal: `python-7/pdb-fatal_python_error`
(via `pdb.set_trace` -> `readline`) and `python-7/site-sigabrt-fatal_python_error`
(via `site.register_readline` -> `readline`). Both import the single-phase
`readline` extension under OOM and abort at `Objects/call.c:80` with
"Slot __delitem__ of type dict succeeded with an exception set".

## Versions

- main (3.16.0a0, commit 15d7406). Aborts on the free-threaded debug+ASan build and
  on the JIT debug build (`_Py_CheckSlotResult` fatal). FT release: clean. Upstream
  release: unrelated segfault (assert compiled out) -> recorded `n/a`.
