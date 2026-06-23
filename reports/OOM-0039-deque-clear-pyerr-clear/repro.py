"""OOM-0039 minimal reproducer (stdlib only) — deterministic via the set_nomemory sweep.

Trigger: a non-empty collections.deque is deallocated with a MemoryError in flight while
the heap is still exhausted. deque_dealloc -> deque_clear allocates a fresh block to drain
the deque safely; that newblock() also fails, so deque_clear does PyErr_Clear() and falls
back -- clobbering the caller's in-flight exception. Trips the gh-89373 _Py_Dealloc debug
invariant: "Deallocator of type 'collections.deque' cleared the current exception".
"""
import faulthandler; faulthandler.enable()
from collections import deque
from _testcapi import set_nomemory

DISABLE = 2_000_000_000
set_nomemory(DISABLE, 0)            # install the hook disarmed (avoid re-swapping the allocator)

def drop_a_deque():
    d = deque(range(64))            # non-empty -> deque_clear takes the newblock() path
    return None                     # d hits its last ref here; if a MemoryError is in flight
                                    # AND newblock() still fails -> PyErr_Clear() clobbers it

for start in range(2000):
    set_nomemory(start, start + 4)  # fail allocations [start, start+4), then resume
    try:
        try:
            drop_a_deque()
        finally:
            set_nomemory(DISABLE, 0)
    except MemoryError:
        pass
print("survived (no crash)")
