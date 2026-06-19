"""OOM-0026: _interpchannels.create() desyncs its integer error code from the Python
exception state under OOM -> handle_channel_error asserts.

This minimal repro deterministically hits the success-branch form:
  Modules/_interpchannelsmodule.c:398  handle_channel_error: assert(!PyErr_Occurred())
because newchannelid() returns err==0 while a MemoryError is pending. The fuzzing
vehicle hits the failure-branch form (line 443, assert(PyErr_Occurred())) where
channel_create() returns -1 with no exception set. Needs a debug build (asserts are
stripped under NDEBUG).
"""
import _interpchannels
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(1, 4000):
    set_nomemory(start, 0)
    try:
        try:
            _interpchannels.create(1)
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
