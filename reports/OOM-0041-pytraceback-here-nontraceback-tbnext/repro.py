"""OOM-0041 reproducer placeholder (minimization OPEN).

Abort: under OOM the in-flight exception's `__traceback__` (exc->traceback) holds a
non-traceback object; when the eval loop appends a frame via PyTraceBack_Here ->
_PyTraceBack_FromFrame, `assert(tb_next == NULL || PyTraceBack_Check(tb_next))` fails
(Python/traceback.c:313). The corrupt tb_next is a dangling pointer -- the traceback was
over-decref'd/freed under OOM and its storage reused (a use-after-free; cf. OOM-0005).

The loop below does NOT reproduce on its own (it survives): plain exception propagation
under an OOM sweep does not corrupt exc->traceback. The over-decref trigger is not yet
isolated, so the reliable reproducer is the preserved `vehicle_source.py` (target: inspect).
This file documents what was ruled out. Next step: gdb watchpoint on exc->traceback to pin
the freeing decref (see report.md "Suggested fix").

Run under the free-threaded debug+ASan build with PYTHON_GIL=0; needs `_testcapi.set_nomemory`.
"""
import faulthandler; faulthandler.enable()
from _testcapi import set_nomemory

DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)


def f3():
    raise ValueError("boom")


def f2():
    f3()


def f1():
    f2()


for start in range(3000):
    set_nomemory(start, start + 5)  # bounded window; traceback built per frame on unwind
    try:
        try:
            f1()
        finally:
            set_nomemory(DISABLE, 0)
    except BaseException:
        pass
print("survived (no crash)")
