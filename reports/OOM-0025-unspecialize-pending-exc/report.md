# Abort: `assert(!PyErr_Occurred())` in `unspecialize` (`specialize.c:378`)

*Under OOM a prior allocation failure leaves a `MemoryError` pending into the `LOAD_GLOBAL` specializer; its builtins lookup returns `DKIX_ERROR` and `goto fail`s, reaching `unspecialize` with the exception still set.*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Inline-cache specialization is meant to be exception-neutral: it either specializes or
quietly backs off, and `unspecialize()` opens with `assert(!PyErr_Occurred())`. Under OOM a
*prior* operation leaves a `MemoryError` pending when the `LOAD_GLOBAL` micro-op runs the
specializer (`specialize_load_global_lock_held`) — gdb confirms the exception is already set
at the specializer's entry on the crashing iteration. The builtins/globals key lookup then
fails *because* an exception is pending, the code `goto fail`s, and it reaches
`unspecialize(instr)` with the `MemoryError` still set, tripping the assert (debug builds;
abort). The specializer does not create the `MemoryError`; it inherits one.

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
  `LOAD_GLOBAL`, the very instruction specialized at the crash, and (being in neither globals
  nor builtins) its lookup is what hits the `DKIX_ERROR` `goto fail` while a `MemoryError` is
  pending. Its role is to keep a pre-existing `MemoryError` pending into the specializer; it
  does **not** itself allocate (the version helper is exception-neutral). A *defined* name
  (e.g. `raise RuntimeError`) does **not** reproduce.

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

`Python/specialize.c`, `specialize_load_global_lock_held`. `_SPECIALIZE_LOAD_GLOBAL` runs
*before* the `_LOAD_GLOBAL` lookup micro-op, so when the specializer is entered with a
`MemoryError` already pending (from a prior allocation failure under the sweep), the
name lookup inside specialization fails and bails:

```c
    Py_ssize_t index = _PyDictKeys_StringLookup(builtin_keys, name);
    if (index == DKIX_ERROR) {           /* returns DKIX_ERROR: an exception is already pending */
        SPECIALIZATION_FAIL(LOAD_GLOBAL, SPEC_FAIL_EXPECTED_ERROR);
        goto fail;                       /* ~L1409 */
    }
    ...
fail:
    unspecialize(instr);                 /* L1441 -> assert(!PyErr_Occurred()) at L378 */
```

gdb-verified on the crashing run: the exception is non-NULL at the function's entry, and the
`goto fail` taken is the `DKIX_ERROR` branch (the string lookup short-circuits on the pending
exception) — **not** the keys-version branch. The defect is that *any* `goto fail` reaches
`unspecialize` while a pre-existing exception is pending: the de-opt/backoff path does not
tolerate or clear it. (`_PyDict_GetKeysVersionForCurrentState` is **not** involved — its
callee `get_next_dict_keys_version` does no allocation and never sets an exception; it is
already exception-neutral and is not even reached on the crashing run.)

**Where the pending `MemoryError` comes from (rr-pinned, 2026-06-25).** `rr` reverse-execution
of the repro — record, watch `tstate->current_exception`, `reverse-continue` to where it is set
— shows the `MemoryError` is produced by a perfectly well-behaved allocation *inside the
`func(*args)` call* (`sys._baserepl`), not by the specializer:

```
_PyErr_NoMemory          <- PyUnicode_New        (alloc fails under OOM)
  <- unicode_decode_utf8
  <- PyImport_AddModuleRef                        (setting up __main__ for the base REPL)
  <- _PyRun_SimpleFileObject  (sys._baserepl)
```

`sys._baserepl` correctly *raises* that `MemoryError`; it propagates out of the `try`, and the
`finally:` block then runs **with the exception still in flight**. The `undefined_name`
`LOAD_GLOBAL` in the `finally` is what invokes the specializer, so it inherits the pending
`MemoryError` — i.e. the specializer is entered with a *legitimately* pending exception, and
`unspecialize`'s `assert(!PyErr_Occurred())` is the wrong invariant. The producer is not a bug;
the de-opt path's intolerance of a pending exception is. This keeps OOM-0025 **distinct** from
the swallowed-exception producers in the same family (OOM-0008's `f_back` swallow,
OOM-0040's extensions-cache key-alloc), whose producers are themselves defective.

## Suggested fix

The adaptive specializer's de-opt/backoff path must tolerate a pre-existing pending
exception. Either:

- don't run specialization (or take the backoff) while `PyErr_Occurred()` — check and skip
  on entry to `_Py_Specialize_LoadGlobal`; or
- relax the `unspecialize` invariant to allow it, e.g.
  `assert(!PyErr_Occurred() || PyErr_ExceptionMatches(PyExc_MemoryError));` and not assume a
  clean error state on de-opt.

This is really an upstream-design question: is the adaptive specializer permitted to run
with a pending exception? (Making `_PyDict_GetKeysVersionForCurrentState` "never set an
exception" — an earlier draft's suggestion — does **not** apply: it already never sets one
and is not the source of the `MemoryError`.)

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

---

*Part of [python/cpython#151763](https://github.com/python/cpython/issues/151763) — an umbrella tracking 35 OOM-related crash findings.*
