"""OOM-0027 minimal reproducer (stdlib only) — shrinkray-reduced from the vehicle, then cleaned.

Trigger: _pyrepl.windows_eventqueue.__annotate__(MagicMock()) (the function wrapper is load-bearing — the crashing POP_JUMP_IF_FALSE is in its frame) under the set_nomemory sweep. Deterministic (re-verified).
"""
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
