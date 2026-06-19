# Title

Abort: `assert(!PyErr_Occurred())` in `unspecialize` (`Python/specialize.c:378`) — LOAD_GLOBAL specialization leaves a `MemoryError` pending when bailing out under OOM

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Inline-cache specialization is meant to be exception-neutral: it either specializes
or quietly backs off, never touching the caller's error state. Under OOM,
`specialize_load_global_lock_held` computes a dict keys-version
(`_PyDict_GetKeysVersionForCurrentState`) that can fail and set a `MemoryError`; the
code treats the `0` return as a benign "out of versions" backoff and `goto fail` →
`unspecialize(instr)`, which opens with `assert(!PyErr_Occurred())`. The pending
`MemoryError` trips it (debug builds; abort).

## Reproducer

Reliably reproduced via the fuzzing vehicle (`sys` fuzz under the `set_nomemory`
sweep); a focused stdlib reduction exercises the path but does not deterministically
hit the exact OOM window (see `repro.py`). Mechanism:

```python
# LOAD_GLOBAL specializes after warmup; then a keys-version realloc fails under OOM
def f():
    return len(x)            # two LOAD_GLOBALs
# ... warm up f() to specialize, then run f() inside a dense set_nomemory(start, 0) sweep
# while churning globals so the keys-version must be recomputed (allocates) under OOM.
```

## Backtrace

```
Python/specialize.c:378: unspecialize: Assertion `!PyErr_Occurred()' failed.
#8  unspecialize                      Python/specialize.c:378   # assert(!PyErr_Occurred())
#9  specialize_load_global_lock_held  Python/specialize.c:1441  # fail: unspecialize(instr);
#10 _Py_Specialize_LoadGlobal         Python/specialize.c:1450
#11 _PyEval_EvalFrameDefault          generated_cases.c.h:10142 # LOAD_GLOBAL specialize
```

## Root cause

`Python/specialize.c`, `specialize_load_global_lock_held` (≈ L1426-1442):

```c
    uint32_t builtins_version = _PyDict_GetKeysVersionForCurrentState(
            interp, (PyDictObject*) builtins);
    if (builtins_version == 0) {
        SPECIALIZATION_FAIL(LOAD_GLOBAL, SPEC_FAIL_OUT_OF_VERSIONS);
        goto fail;                       /* may have a MemoryError pending */
    }
    ...
fail:
    unspecialize(instr);                 /* assert(!PyErr_Occurred()) */
```

`_PyDict_GetKeysVersionForCurrentState` returns `0` both for the benign
"no version available" case *and* when assigning a new version fails under memory
pressure — and in the latter case it leaves an exception set. The specialization
backoff path does not distinguish the two, so an OOM-induced `MemoryError` survives
into `unspecialize`. (The same `goto fail` guards the globals-version computation
just above, so either version call can trigger it.)

## Suggested fix

Specialization must not propagate an exception. Either:

- have `_PyDict_GetKeysVersionForCurrentState` never set an exception (return `0`
  silently on allocation failure), or
- clear it on the backoff path, e.g. in `unspecialize` / before `goto fail`:
  `assert(!PyErr_Occurred() || PyErr_ExceptionMatches(PyExc_MemoryError)); PyErr_Clear();`

The first is cleaner — the version helper is a best-effort optimization hook and
should be exception-neutral by contract.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). Debug-only: the assert is
`#ifndef NDEBUG`, so release builds (`ft_release`, `upstream`) silently continue
(de-opt proceeds with a stray `MemoryError`, later surfaced or cleared elsewhere).
Member of the "exception-state-under-OOM" family (cf. OOM-0008/0010/0011/0015), but a
distinct site/function from OOM-0011 (`specialize` LoadAttr, specialize.c:364).
Minimization: PARTIAL — vehicle-confirmed; no deterministic minimal trigger isolated.

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT
  debug+ASan; assert compiled out on the release builds.
