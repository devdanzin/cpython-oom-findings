# Abort: `assert(PyStackRef_BoolCheck(cond))` in `POP_JUMP_IF_FALSE` (`Python/generated_cases.c.h`) — the value stack holds a non-bool at a conditional jump under OOM

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

`POP_JUMP_IF_FALSE` (and its siblings) assume the top of the value stack is already a
strict bool — the compiler guarantees a `TO_BOOL` (or a bool-producing compare)
immediately precedes them, and the handler only asserts it:
`cond = stack_pointer[-1]; assert(PyStackRef_BoolCheck(cond));`. Under OOM that
invariant is violated: the slot holds something other than `Py_True`/`Py_False` (a
non-bool object, or a stale/`NULL` stack reference left by a preceding opcode whose
error path did not unwind cleanly), and the assert aborts on debug builds.

## Reproducer

Minimal, stdlib-only (shrinkray-reduced from the vehicle, then cleaned; deterministic,
re-verified). A POP_JUMP_IF_FALSE finds a non-bool stackref under OOM.

```python
import faulthandler
from unittest.mock import MagicMock
import _pyrepl.windows_eventqueue
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

def run(func, *args):                     # wrapper preserved: the crashing POP_JUMP_IF_FALSE is in this frame's bytecode
    for start in range(160):
        set_nomemory(start)
        try:
            try:
                func(*args)
            finally:
                remove_mem_hooks()
        except BaseException:
            pass

run(_pyrepl.windows_eventqueue.__annotate__, MagicMock())
print("done, no crash")
```

The full fuzzer vehicle is preserved as `vehicle_source.py`.

## Backtrace

```
generated_cases.c.h:11120: _PyEval_EvalFrameDefault: Assertion `PyStackRef_BoolCheck(cond)' failed.
#8  _PyEval_EvalFrameDefault  generated_cases.c.h:11120   # TARGET(POP_JUMP_IF_FALSE)
#9  _PyEval_EvalFrame         pycore_ceval.h:122
#10 _PyEval_Vector            ceval.c:2141
#11 PyEval_EvalCode           ceval.c:679
```

## Root cause

`Python/generated_cases.c.h`, `TARGET(POP_JUMP_IF_FALSE)`:

```c
    _PyStackRef cond;
    cond = stack_pointer[-1];
    assert(PyStackRef_BoolCheck(cond));     /* TOS must be Py_True/Py_False */
    int flag = PyStackRef_IsFalse(cond);
    ...
```

The handler does not itself produce `cond`; it trusts the preceding instruction. Under
memory pressure an earlier opcode (e.g. the `TO_BOOL` family, a comparison, or a
specialized form) can fail to allocate and leave the stack in a state the error
unwinding doesn't fully repair, so a non-bool / dangling `_PyStackRef` reaches the
jump. This is a **symptom**: the defective producer is upstream and was not pinned
down from this single vehicle. On release builds (`PyStackRef_IsFalse` without the
assert) the same bad value is then *used* as a branch condition — a silent control-flow
corruption rather than a clean abort.

## Suggested fix

Primary fix belongs at the producer: ensure every opcode that can fail under OOM
restores the value stack before jumping to the error label (no partially-formed /
dangling `_PyStackRef` left on the stack). Identifying which producer requires more
than one vehicle — a fuzzing corpus that records the *preceding* executed opcode at the
abort would localize it. As a defensive measure the assert could be promoted to a
runtime check that routes to `error` instead of trusting the invariant, but that masks
the real producer bug.

## Notes

Found via OOM-injection fuzzing (`_testcapi.set_nomemory`). Debug-only assert (stripped
under NDEBUG). **Root cause is PARTIAL** — this is the consumer-side symptom of an
upstream opcode leaving a bad stack value under OOM; the producing instruction was not
isolated. Distinct from OOM-0010 (a *generic* `LABEL(error)` assert at
generated_cases.c.h:13106): this is a specific `PyStackRef_BoolCheck` failure in the
conditional-jump handler. Saved host stdout shows the same assertion at line 10539
(host build at a different commit); local debug build (15d7406) reports line 11120.

## Versions

- main (3.16.0a0), commit 15d7406. Aborts on free-threaded debug+ASan and JIT
  debug+ASan; assert compiled out on the release builds (the non-bool is used as a
  branch condition instead).
