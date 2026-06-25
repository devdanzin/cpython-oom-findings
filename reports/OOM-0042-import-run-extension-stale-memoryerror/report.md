# Abort: stale `MemoryError` trips `assert(!PyErr_Occurred())` in `import_run_extension` (`import.c:2301`)

*Importing a single-phase C extension (`readline`) under OOM: an allocation in the extension's init fails and leaves a `MemoryError` pending, but the init still reports success, so `import_run_extension` reaches its post-init invariant `assert(!PyErr_Occurred())` with the stale exception set and aborts.*

_AI Disclaimer: this report was drafted by Claude Code, which also reproduced the crash and characterized it._

## Crash report

When CPython imports a dynamic (C) extension, `_imp_create_dynamic` → `_imp_create_dynamic_impl` → `import_run_extension` runs the module init function and then validates the result. For a **single-phase** extension (the legacy `PyInit_*` that returns a ready module), `import_run_extension` checks subinterpreter compatibility and then asserts a clean error state:

```c
else {  /* Python/import.c, import_run_extension, SINGLEPHASE branch */
    assert(res.kind == _Py_ext_module_kind_SINGLEPHASE);
    assert_singlephase_def(def);
    if (_PyImport_CheckSubinterpIncompatibleExtensionAllowed(name_buf) < 0) {
        goto error;
    }
    assert(!PyErr_Occurred());          /* L2301 <- fires */
    ...
}
```

Under OOM, an allocation inside the single-phase init (here `PyInit_readline`) fails and sets `MemoryError`, but the init still returns a module (success: `res.kind == SINGLEPHASE`, no `main_error`). Execution reaches L2301 with the `MemoryError` still pending and the `Py_DEBUG` invariant aborts. gdb confirms `tstate->current_exception` is a `MemoryError` and the init function is `PyInit_readline`.

This is the **stale-pending-exception** class (a C path returns success with an exception set), here in the C-extension import path — a sibling of OOM-0021 (`_Py_CheckFunctionResult`), OOM-0022 (`_Py_CheckSlotResult` in `reload_singlephase_extension`), and the eval-loop `!PyErr_Occurred()` asserts (OOM-0008/0011). It is **distinct** from OOM-0040, which segfaults later in the *same import* at `_extensions_cache_set` → `hashtable_hash_str(NULL)` (`import.c:1312`) after a successful init; this one aborts earlier, at the post-init invariant.

## Reproducer

Vehicle-confirmed (`vehicle_source.py`, target `code`; reproduces 6/6 on `ft_debug_asan` @`1b9fe5c`). The crashing import is the single-phase C extension `readline`, pulled in transitively by `code`/`pdb`/`site`. **Minimization partial** (see Notes) — a bare `import readline` under a windowed OOM sweep does not land the failure inside readline's init:

```python
# Does NOT reproduce (the failing allocation must land inside readline's single-phase
# init; a bare import under a windowed sweep misses that window, and a C extension only
# runs PyInit once per process so a single-process sweep can't re-arm it). Kept to
# document what was ruled out; vehicle_source.py is the reliable reproducer.
import sys, faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
assert 'readline' not in sys.modules
set_nomemory(40, 48)          # windowed failure (window 8, as the vehicle uses)
try:
    import readline
except BaseException:
    pass
finally:
    remove_mem_hooks()
print("survived (no crash)")
```

## Backtrace

```
python: Python/import.c:2301: PyObject *import_run_extension(...): Assertion `!PyErr_Occurred()' failed.
Fatal Python error: Aborted

#1 import_run_extension          Python/import.c:2301   (p0 == PyInit_readline; pending exc == MemoryError)
#2 _imp_create_dynamic_impl      Python/import.c:5529
#3 _imp_create_dynamic           Python/clinic/import.c.h:489
#4 cfunction_vectorcall_FASTCALL Objects/methodobject.c:449
#5 _PyVectorcall_Call            Objects/call.c:273
#6 _PyEval_EvalFrameDefault      Python/generated_cases.c.h:2831   (the `import readline` statement)
```

See `backtrace.txt`.

## Root cause

`Python/import.c`, `import_run_extension` (def at L2095). After `_PyImport_RunModInitFunc` runs the single-phase `PyInit_*` and the no-error path is taken (`res.kind == _Py_ext_module_kind_SINGLEPHASE`, `main_error` false), the function asserts `!PyErr_Occurred()` at L2301. The invariant is that a successful single-phase init leaves no pending exception. Under OOM that invariant is violated: an allocation during the init fails, sets `MemoryError`, and the init returns success without clearing it (or without reporting failure). The assert is the **detector**; the defect is that the single-phase extension-import path does not guarantee a clean error state on the success path under allocation failure (either the extension's `PyInit` returns success-with-exception, or an allocation in the post-init bookkeeping before L2301 sets it). The producing allocation is not pinned (see Notes).

## Suggested fix

Treat a pending exception on the single-phase success path as an import failure rather than asserting — e.g. after `_PyImport_RunModInitFunc` succeeds, if `PyErr_Occurred()` then convert to the error path (`goto error`) instead of `assert(!PyErr_Occurred())`, mirroring how `_Py_CheckFunctionResult` / `_Py_CheckSlotResult` turn "success with exception" into a `SystemError`/failure for the call and multi-phase paths. (The narrower alternative — auditing each allocation in the single-phase init/bookkeeping to bail cleanly on OOM — depends on which allocation is left pending, which is not yet isolated.)

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`), fusil `--oom-seq` mode. **Recurring across machines** (local fleet + the `oca` box) and several vehicle modules — `code`, `pdb`, `site`, `sys` — all of which transitively first-import the single-phase C extension `readline` during the fuzz run; the crash is in that import, not the named module.

**Distinct from OOM-0040** (same `import` of a C extension under OOM, but OOM-0040 is a SEGV at `_extensions_cache_set` → `hashtable_hash_str(NULL)` (`import.c:1312`) *after* a successful init, whereas this is an abort at the post-init `!PyErr_Occurred()` invariant). They share only the generic `_imp_create_dynamic_impl` caller, so this report is keyed on `import_run_extension:2301` (not the shared caller) to avoid conflation. **Distinct from OOM-0022** (`_Py_CheckSlotResult` in `reload_singlephase_extension`, `import.c:2011`) and **OOM-0021** (`_Py_CheckFunctionResult`, `call.c:43`) — same "success with a pending exception" family, different sites/detectors. Member of the **stale-pending-`MemoryError` cluster** (see `SUMMARY.md`).

**Debug-only signature.** The assert is `Py_DEBUG`-gated (abort on `ft_debug_asan` + `jit`). On release builds (`ft_release`, `upstream`; `NDEBUG`) it is compiled out and the stale `MemoryError` propagates out of the import (a spurious/late `MemoryError`, or cleared downstream) — recorded `n/a` for the release builds.

**Minimization partial.** Vehicle-confirmed (6/6 on `ft_debug_asan`); a bare `import readline` under a windowed `set_nomemory` sweep in fresh processes (start `0..120`, window `8`) did not reproduce — the failing allocation must land inside readline's single-phase init, which the vehicle's broader allocation profile achieves but a bare import does not. A C extension runs `PyInit` only once per process, so a single-process sweep cannot re-arm it (same first-import-under-OOM difficulty as OOM-0040). The producing allocation is not pinned.

## Versions

- main (3.16.0a0), commit `1b9fe5c` (free-threaded debug+ASan, Clang 21). Aborts deterministically from the vehicle on the `Py_DEBUG` builds; release builds compile the assert out (stale `MemoryError` propagates).

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking OOM-related crash findings.*
