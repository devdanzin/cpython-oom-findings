"""
Minimal reproducer: fatal "_Py_Dealloc: Deallocator of type 'X' cleared the
current exception" for ordinary stdlib instances under OOM.

This covers the non-Context family of the gh-89373 dealloc-clears-exception
fatal: argparse._StoreAction, urllib.request.UnknownHandler / ProxyHandler,
logging.LogRecord. They share ONE root cause: the generic subtype_dealloc()
(Objects/typeobject.c), inherited by every pure-Python heap type without a
__del__, tears down the instance __dict__ and slots without preserving the
in-flight exception. (The Context type, OOM-0007, has its own C deallocator
context_tp_dealloc and is reported separately.)

Affected:   CPython 3.16.0a0 (main), commit 15d7406.
            Fatal on Py_DEBUG builds (the _Py_Dealloc invariant is
            #ifdef Py_DEBUG); release builds compile it out (see Notes).
Crash:      Fatal Python error: _Py_Dealloc: Deallocator of type '_StoreAction'
            cleared the current exception   (SIGABRT, rc 134)
Requires:   a free-threaded debug build exposing _testcapi.set_nomemory.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build, around start=276.

Backtrace (gdb):
    #8  _Py_Dealloc          Objects/object.c:3338   (gh-89373 invariant)
    #11 _PyFrame_ClearLocals Python/frame.c:101       (frame unwind under MemoryError)
    #13 clear_thread_frame   Python/ceval.c:1954
    -> tp_dealloc for the _StoreAction instance is subtype_dealloc
       (Objects/typeobject.c:2719); it clears slots (L2840) and decrefs the
       instance __dict__ (L2847/L2854) with no exception save/restore.

Root cause (Objects/typeobject.c):

    subtype_dealloc() runs the finalize (__del__) path only if tp_finalize is
    set; the exception is preserved ONLY there, inside slot_tp_finalize()
    (L11209: _PyErr_GetRaisedException / L11235: _PyErr_SetRaisedException).
    Classes like _StoreAction / UnknownHandler / ProxyHandler / LogRecord have
    no __del__, so tp_finalize is NULL and that wrapper never runs. The
    subsequent slot/dict teardown (clear_slots L2840, PyObject_ClearManagedDict
    L2847, Py_DECREF(dict) L2854) decrefs the instance's attribute values while
    a MemoryError is in flight; that cascade clears tstate->current_exception,
    so the debug-only _Py_Dealloc invariant at object.c:3338 fatals.

Fix: bracket subtype_dealloc's destructive section (slot/dict teardown + the
base tp_dealloc call) with _PyErr_GetRaisedException / _PyErr_SetRaisedException,
mirroring slot_tp_finalize. One fix covers the whole non-Context family.

Note on the warm-up: http.server._main triggers lazy imports (argparse,
gettext, re). The single up-front _main(['--help']) loads them so the OOM lands
inside parser construction (creating _StoreAction objects) rather than during
module import (which would hit the unrelated import-time abort, OOM-0003).
The sweep is required: a single fixed set_nomemory(276, 0) does not reproduce
because the exact allocation index depends on the swept state.
"""
import http.server
from _testcapi import set_nomemory, remove_mem_hooks
import faulthandler

faulthandler.enable()

# Warm all lazy imports so the OOM lands in _main's argparse construction.
try:
    http.server._main(['--help'])
except SystemExit:
    pass

for start in range(1000):
    set_nomemory(start, 0)            # fail every allocation from #start onward
    try:
        try:
            http.server._main([])     # _StoreAction torn down mid-unwind under MemoryError
                                      # -> subtype_dealloc clears the exception -> fatal
        finally:
            remove_mem_hooks()
    except (SystemExit, MemoryError):
        pass
    except BaseException:
        pass

print("NO CRASH (unexpected on a Py_DEBUG build)")
