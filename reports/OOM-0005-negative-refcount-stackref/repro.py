"""OOM-0005 minimal reproducer (stdlib only) — reduced from the xml.dom.minidom fuzz vehicle
with shrinkray + hand-cleanup.

Calling a Python function under a dense allocation-failure sweep makes the call fail with
MemoryError partway through. On the frame-teardown unwind path (exit_unwind ->
_PyFrame_ClearLocals, Python/frame.c:101), PyStackRef_XCLOSE
(Include/internal/pycore_stackref.h:726) closes a `_PyStackRef` still on the frame's value
stack that points at an object (a MemoryError instance) whose refcount is already 0, driving
it negative. The debug build's _Py_NegativeRefcount detector aborts ("object has negative ref
count", reported at the *caller* site pycore_stackref.h:726). On release builds the assert is
compiled out and the underflow frees a still-live object -> use-after-free / segfault.

Deterministic: aborts on every run (20/20 with PYTHON_GIL=1, 8/8 with PYTHON_GIL=0).
Requires a debug build (the _Py_NegativeRefcount detector is Py_REF_DEBUG-only).

shrinkray reduced the 511-line vehicle but could not remove the fuzzer's `weird_classes`
setup because the final call's argument referenced it; substituting a trivial argument (`0`)
freed that setup for removal, and the bare `xml.dom.minidom.parse(0)` sweep reproduces on its
own. Unlike the older multiprocessing.spawn/runpy reduction (which tripped a *sibling*
code_dealloc assert first, hence the previous "partial" status), the xml.dom.minidom path
deterministically hits *this* stackref underflow. The full vehicle is preserved as
`vehicle_source.py`.
"""
import xml.dom.minidom
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(100):
    set_nomemory(start, 0)
    try:
        try:
            xml.dom.minidom.parse(0)
        finally:
            remove_mem_hooks()
    except:
        pass
