"""
Reproducer: Fatal Python error
  "_Py_Dealloc: Deallocator of type 'Context' cleared the current exception"
under OOM (CPython 3.16.0a0 / main, commit 15d7406).

WHAT HAPPENS
------------
Under memory pressure a contextvars.Context is deallocated while an exception
(a MemoryError raised mid-operation) is in flight -- e.g. its last reference is
held by a frame local/cell that is being cleared while the frame unwinds.
context_tp_dealloc() runs its teardown (PyObject_ClearWeakRefs + context_tp_clear,
which decrefs ctx_prev and the ctx_vars HAMT and all stored ContextVar values)
WITHOUT saving/restoring tstate->current_exception. That teardown clears the
pending exception, tripping the gh-89373 debug invariant in _Py_Dealloc:

    Fatal Python error: _Py_Dealloc: Deallocator of type 'Context' cleared the
    current exception

The invariant is Py_DEBUG-only, so the FATAL appears on debug builds
(ft_debug_asan, jit). On release builds the check is compiled out -> silent
error-indicator corruption.

C path (gdb, break on _Py_FatalErrorFormat):
    #1 _Py_Dealloc            Objects/object.c:3338   tp_name == "Context"
    #4 cell_dealloc           Objects/cellobject.c:81 Py_XDECREF(op->ob_ref)  (Context)
    #8 _PyFrame_ClearLocals   Python/frame.c:101      unwinding under MemoryError
    #10 clear_thread_frame    Python/ceval.c:1954

Root cause (Python/context.c, context_tp_dealloc L535-546):
    no PyErr_GetRaisedException/PyErr_SetRaisedException around the teardown.

Likely fix: bracket the dealloc body with
    PyObject *exc = PyErr_GetRaisedException();
    ... ClearWeakRefs + context_tp_clear ...
    PyErr_SetRaisedException(exc);

----------------------------------------------------------------------
RELIABLE REPRODUCER: the original fuzzing vehicle.
Run under a debug build, e.g.:
    ~/projects/3.16_ft_debug_asan_cpython/python <this dir>/../../crashers/...
The smallest reliable trigger we have is importlib.metadata.entry_points()
under the dense set_nomemory sweep:
"""
import importlib.metadata
import faulthandler

faulthandler.enable()

try:
    from _testcapi import set_nomemory, remove_mem_hooks
except ImportError:
    raise SystemExit("needs a build exposing _testcapi.set_nomemory (debug/test)")

# entry_points() -> _unique(distributions()) -> Distribution.discover(): builds and
# tears down a contextvars.Context while MemoryError is propagating mid-iteration.
for start in range(1000):          # dense OOM sweep; fail every alloc from #start
    set_nomemory(start, 0)
    try:
        try:
            importlib.metadata.entry_points()
        finally:
            remove_mem_hooks()     # restore allocator before the except clause
    except MemoryError:
        pass
    except BaseException as err:
        print(type(err).__name__)

print("done (no crash on this build/run)")

# ----------------------------------------------------------------------
# MINIMIZATION: PARTIAL.
# A self-contained stdlib-only reduction was attempted (build a populated
# Context, drop its sole reference from a cell/generator frame while a
# MemoryError unwinds, optionally with a stored value whose __del__ touches the
# error indicator) but did NOT reproduce within the swept budget -- the bug
# needs the precise timing where tstate->current_exception holds a *raw*
# (un-normalized) exception at the instant of the Context's last decref. The
# vehicle above reproduces reliably on debug builds; ship vehicle + partial.
