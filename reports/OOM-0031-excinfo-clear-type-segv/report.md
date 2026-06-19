# Title

Segfault: `_interpreters.exec` under OOM frees an invalid cross-interpreter excinfo — `_excinfo_clear_type` (`Python/crossinterp.c:1319`) dereferences an uninitialized/dangling `info`

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Running code in a subinterpreter with `_interpreters.exec` captures any exception into a
`_PyXI_excinfo` for propagation. Under memory pressure that capture/setup fails partway,
and the cleanup path `_PyXI_FreeExcInfo` → `_PyXI_excinfo_clear` → `_excinfo_clear_type`
runs on an excinfo that was never fully initialized (or already freed). `_excinfo_clear_type`
reads `info->builtin` (crossinterp.c:1319) on that bad `info` → SIGSEGV. Reproduces on all
build configurations (a wild-pointer dereference, not a debug-only assert).

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
#0  _excinfo_clear_type   Python/crossinterp.c:1319   # reads info->builtin on a bad info
#1  _PyXI_excinfo_clear   Python/crossinterp.c:1374
#2  _PyXI_FreeExcInfo     Python/crossinterp.c:1712
#5  cfunction_vectorcall_FASTCALL_KEYWORDS  Objects/methodobject.c:465   # _interpreters.exec
```

## Root cause

`Python/crossinterp.c`, `_excinfo_clear_type` (L1316-…):

```c
static void
_excinfo_clear_type(struct _excinfo_type *info)
{
    if (info->builtin != NULL) {                 /* L1319: derefs info -> SIGSEGV if info is invalid */
        assert(info->builtin->tp_flags & _Py_TPFLAGS_STATIC_BUILTIN);
        ...
    }
    if (info->name != NULL)     PyMem_RawFree((void *)info->name);
    if (info->qualname != NULL) PyMem_RawFree((void *)info->qualname);
    ...
}
```

The crash is the first field read, so the `struct _excinfo_type *info` (a member of the
`_PyXI_excinfo` being freed) is itself a bad pointer — the enclosing `_PyXI_excinfo` was
not fully/validly initialized when an allocation failed during `_interpreters.exec`'s
exception capture, yet `_PyXI_FreeExcInfo` was still called on it. (If `info` is valid but
`info->builtin` is uninitialized garbage from an unzeroed struct, the next line's
`info->builtin->tp_flags` deref is the same defect one step in.)

## Suggested fix

The cross-interpreter exec error path must not call `_PyXI_FreeExcInfo` on a
not-fully-initialized `_PyXI_excinfo`, and the struct must be zero-initialized so that
`_excinfo_clear_type`'s `!= NULL` guards are meaningful (NULL fields, not garbage). Audit
the `_interpreters.exec` failure unwinding in `crossinterp.c` for a free-before-init (or
double-free) of the excinfo under allocation failure.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`); flagged `oomNEW` by fusil's
in-loop dedup against the current catalog. Distinct from the other interpreters-module
bugs (OOM-0014/0016 `_interpchannels`/`_interpqueues`, OOM-0026 `handle_channel_error`) —
this is the `crossinterp.c` excinfo cleanup. Clean wild-pointer dereference: **reproduces
on all four builds** (ft_debug_asan, ft_release, jit, upstream), unlike the debug-only
asserts. Same "free/clear a partially-initialized struct on the OOM error path" theme as
OOM-0024/0030. Root cause: the exact producer (where the excinfo is left invalid) is
identified to the `_interpreters.exec` capture path but not pinned to a single line.

## Versions

- main (3.16.0a0), commit 15d7406. SIGSEGV on all four local builds.
