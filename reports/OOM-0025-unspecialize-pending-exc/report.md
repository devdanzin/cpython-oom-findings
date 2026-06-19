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

Minimal, stdlib-only (shrinkray-reduced from the `sys`-fuzz vehicle; **deterministic** —
aborts on every run, 20/20 observed). Needs a debug build (`PYTHON_GIL=1`):

```python
from _testcapi import set_nomemory
import sys


def oom_call(func, *args):
    for start in range(40):
        set_nomemory(start)
        try:
            try:
                func(*args)
            finally:
                undefined_name  # LOAD_GLOBAL of an undefined name
        except:
            pass


oom_call(sys._baserepl)
```

Two elements are load-bearing (each verified necessary by holding the rest fixed):

- **`func(*args)`, not `func()`** — the unpacking call is a *specialized CALL*; a plain
  `func()` does not reproduce even with a wider sweep. The bug is in the adaptive
  specializer, so the exact bytecode form matters.
- **a bare undefined global in the `finally`** — `undefined_name` compiles to a
  `LOAD_GLOBAL`, the very instruction being specialized at the crash. Because the name is
  in neither globals nor builtins, the lookup forces computing **both** keys-versions (the
  allocation that fails under OOM); a *defined* name (e.g. `raise RuntimeError`)
  short-circuits and does **not** reproduce. The undefined lookup also leaves an exception
  pending, mirroring the invariant `unspecialize` assumes is clear.

(The earlier hand reduction — warm up `def f(): return len(x)` then churn globals under the
sweep — exercised the same path but did not deterministically hit the window; shrinkray
found this stable trigger. The full fuzzer vehicle is preserved as `vehicle_source.py`.)

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
Minimization: DONE — deterministic stdlib reduction (`repro.py`), reduced from the vehicle
with shrinkray and re-verified (20/20).

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT
  debug+ASan; assert compiled out on the release builds.
