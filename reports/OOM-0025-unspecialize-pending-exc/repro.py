"""OOM-0025 minimal reproducer (stdlib only) — reduced from the fuzzer vehicle with shrinkray.

`unspecialize` opens with `assert(!PyErr_Occurred())`, on the theory that inline-cache
specialization is exception-neutral. Under OOM that invariant breaks: a hot `LOAD_GLOBAL`
is specialized while memory allocation is failing, the keys-version helper leaves a
`MemoryError` pending, and the `goto fail -> unspecialize(instr)` backoff path then trips
the assert (Python/specialize.c:378). Debug-only (the assert is compiled out under NDEBUG).

Two elements shrinkray isolated as load-bearing (each verified necessary — see report.md):
  * the call form is `func(*args)` (a specialized CALL), NOT a plain `func()`;
  * the `finally:` body is a bare *undefined* global (`undefined_name`), which compiles to
    a `LOAD_GLOBAL` — the very instruction specialized at the crash — and forces the
    not-found lookup that computes both the globals and builtins keys-versions (the
    allocation that fails under OOM). A *defined* name short-circuits and does not reproduce.

Needs a debug build (PYTHON_GIL=1). Deterministic: aborts on every run (20/20 observed).
"""
from _testcapi import set_nomemory
import sys


def oom_call(func, *args):
    for start in range(40):
        set_nomemory(start)
        try:
            try:
                func(*args)
            finally:
                undefined_name  # LOAD_GLOBAL of an undefined name: pending exc + specializable
        except:
            pass


oom_call(sys._baserepl)
print("done, no crash")
