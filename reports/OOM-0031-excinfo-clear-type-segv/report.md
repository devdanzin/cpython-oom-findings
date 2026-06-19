# Title

Segfault: `_interpreters.capture_exception` under OOM calls `_PyXI_FreeExcInfo(NULL)` — the unguarded cleanup `_excinfo_clear_type` (`Python/crossinterp.c:1319`) dereferences a NULL `info`

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`_interpreters.capture_exception(exc)` builds a `_PyXI_excinfo` via `_PyXI_NewExcInfo`.
Under memory pressure that allocation fails and `_PyXI_NewExcInfo` returns **NULL**;
`_interpreters_capture_exception_impl` then `goto finally`, whose cleanup block
unconditionally calls `_PyXI_FreeExcInfo(info)` with `info == NULL`
(`Modules/_interpretersmodule.c:1544`). `_PyXI_FreeExcInfo` has no NULL guard, so
`_PyXI_excinfo_clear` → `_excinfo_clear_type` dereferences `&NULL->type` (offset 0) at
`crossinterp.c:1319` → SIGSEGV. (gdb confirms `info == 0x0` at the fault.) Reproduces on all
build configurations (a NULL dereference, not a debug-only assert).

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle; deterministic, re-verified 40×):

```python
import faulthandler, _interpreters
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
for start in range(0, 40):
    try:
        set_nomemory(start, 0)
        try:
            _interpreters.capture_exception(Exception())
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
```

shrinkray reduced the original `_interpreters.exec` vehicle to a **simpler, more direct
trigger**: `_interpreters.capture_exception(exc)` is the call that builds the
`_PyXI_excinfo`, so it reaches the bug without running code in a subinterpreter. The full
fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
Program received signal SIGSEGV, Segmentation fault.
#0  _excinfo_clear_type               Python/crossinterp.c:1319   # info == 0x0 -> offset-0 deref
#1  _PyXI_excinfo_clear               Python/crossinterp.c:1374
#2  _PyXI_FreeExcInfo                 Python/crossinterp.c:1712   # called with info == NULL, no guard
#3  _interpreters_capture_exception_impl  Modules/_interpretersmodule.c:1544   # finally: _PyXI_FreeExcInfo(info)
#5  cfunction_vectorcall_FASTCALL_KEYWORDS  Objects/methodobject.c:465   # _interpreters.capture_exception
```

## Root cause

`Modules/_interpretersmodule.c`, `_interpreters_capture_exception_impl` (≈L1522-1544):

```c
    _PyXI_excinfo *info = _PyXI_NewExcInfo(exc);   /* returns NULL under OOM */
    if (info == NULL) {
        goto finally;
    }
    ...
finally:
    _PyXI_FreeExcInfo(info);     /* L1544: runs even when info == NULL */
    ...
```

`_PyXI_NewExcInfo` (crossinterp.c:1683) `PyMem_RawCalloc`s its struct and, on any failure,
`PyMem_RawFree`s it and returns NULL — it never returns a dangling/half-built struct. So
`info` here is a clean **NULL**, and `_PyXI_FreeExcInfo` (crossinterp.c:1710) has no NULL
guard: `_PyXI_excinfo_clear` → `_excinfo_clear_type(&info->uncaught)` dereferences offset 0
at L1319. gdb on the debug build confirms `info == 0x0` at the fault (the ASan-reported
address `0x03e8…` is a red herring from ASan's signal trampoline).

## Suggested fix

A one-line NULL guard. Either guard the call site —
`if (info != NULL) _PyXI_FreeExcInfo(info);` at `_interpretersmodule.c:1544` — or add
`if (info == NULL) return;` at the top of `_PyXI_FreeExcInfo` (`crossinterp.c:1710`).
`_interpretersmodule.c:1544` is the only direct caller of `_PyXI_FreeExcInfo` in the tree.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`); flagged `oomNEW` by fusil's
in-loop dedup against the current catalog. Distinct from the other interpreters-module
bugs (OOM-0014/0016 `_interpchannels`/`_interpqueues`, OOM-0026 `handle_channel_error`) —
this is the `crossinterp.c` excinfo cleanup, reached from `capture_exception`. Clean NULL
dereference: **reproduces on all four builds** (ft_debug_asan, ft_release, jit, upstream),
unlike the debug-only asserts. shrinkray reduced the original `_interpreters.exec` vehicle
to the simpler `capture_exception` trigger; the crash site belongs to `capture_exception`
(`_interpreters.exec` goes through `_PyXI_Enter`/`_PyXI_Exit`, a different error struct, and
does **not** reach this `_PyXI_FreeExcInfo(NULL)` path — so the bug is filed against
`capture_exception`). Root cause + fix are fully pinned (an unchecked `_PyXI_NewExcInfo`
return).

## Versions

- main (3.16.0a0), commit 15d7406. SIGSEGV on all four local builds.
