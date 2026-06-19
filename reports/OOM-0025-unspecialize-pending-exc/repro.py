"""OOM-0025: LOAD_GLOBAL specialization leaves a MemoryError pending -> unspecialize
asserts. Python/specialize.c:378 `assert(!PyErr_Occurred())`.

PARTIAL minimization: this exercises the LOAD_GLOBAL specialize -> keys-version ->
backoff path under OOM, but does not deterministically hit the exact window. The
fuzzing vehicle (python-7/sys-assertion) reproduces reliably. Needs a debug build
(the assert is compiled out under NDEBUG).
"""
from _testcapi import set_nomemory, remove_mem_hooks

g = {}
exec(compile("def f():\n    return len(x)\n", "<f>", "exec"), g)
f = g["f"]
g["x"] = "abc"

for _ in range(300):            # warm up adaptive specialization of the LOAD_GLOBALs
    f()

for start in range(1, 6000):
    set_nomemory(start, 0)
    try:
        try:
            g["k%d" % (start & 15)] = start   # churn globals -> keys-version realloc under OOM
            for _ in range(40):
                f()
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
