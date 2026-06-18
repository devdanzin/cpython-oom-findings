"""
Reproducer: fatal _Py_CheckSlotResult ("Slot __delitem__ of type dict succeeded
with an exception set") in reload_singlephase_extension() when
_modules_by_index_set() fails under OOM.

Affected:   CPython 3.16.0a0 (main), DEBUG builds (Py_DEBUG=1). The fatal check
            _Py_CheckSlotResult is invoked inside assert() in PyObject_DelItem
            (Objects/abstract.c:280), so it is compiled out under NDEBUG.
Crash:      SIGABRT (rc 134), Objects/call.c:80
            Fatal Python error: _Py_CheckSlotResult: Slot __delitem__ of type
            dict succeeded with an exception set
Requires:   a CPython DEBUG build exposing _testcapi.set_nomemory
            (ft_debug_asan or jit).

Run:
    python repro.py            # aborts (rc 134) on a debug build

Backtrace (gdb):
    #8  _Py_CheckSlotResult          Objects/call.c:80
    #9  PyObject_DelItem             Objects/abstract.c:280
    #10 reload_singlephase_extension Python/import.c:2011   (PyMapping_DelItem cleanup)
    #11 import_find_extension        Python/import.c:2043
    #12 _imp_create_dynamic_impl     Python/import.c:5468

Root cause (Python/import.c, reload_singlephase_extension, L2009-2014):

    Py_ssize_t index = _get_cached_module_index(cached);
    if (_modules_by_index_set(tstate->interp, index, mod) < 0) {  // raises MemoryError under OOM
        PyMapping_DelItem(modules, info->name);                   // runs with MemoryError still set
        Py_DECREF(mod);
        return NULL;
    }

    _modules_by_index_set() (L577) can fail in PyList_New(0) / PyList_Append()
    when the per-interpreter modules_by_index list must be created or grown.
    On failure it returns -1 with a MemoryError set. The cleanup then deletes
    the module name from sys.modules (a dict); the delete SUCCEEDS (res == 0),
    but the MemoryError is still pending. On a debug build
    assert(_Py_CheckSlotResult(o, "__delitem__", res >= 0)) (abstract.c:280)
    fires the fatal "slot succeeded with an exception set" invariant.

Suggested fix: save/restore the pending exception around the cleanup delete
(PyErr_GetRaisedException / PyErr_SetRaisedException), so the dict __delitem__
slot does not run with a stale exception.

Minimization note: PARTIAL / vehicle-based. Triggering requires the failing
allocation to land inside _modules_by_index_set during a single-phase-extension
reload (the modules_by_index list must need to grow). That depends on accumulated
interpreter state; the loop below exercises the exact code path
(import_find_extension -> reload_singlephase_extension via `readline`) but did not
trip the assert in isolation in ~10 stdlib-only attempts. The authoritative,
deterministic reproducer is the fuzzer vehicle source.py shipped alongside this
file (see report.md / meta.json "vehicles"); it aborts at start ~= 237.
"""
import sys
import _testcapi
import faulthandler

faulthandler.enable()

# pdb.set_trace() imports the single-phase legacy C extension `readline`
# (pdb.Pdb.__init__), which routes re-imports through
# import_find_extension -> reload_singlephase_extension.
import pdb

for start in range(1, 260):
    _testcapi.set_nomemory(start, 0)   # fail every allocation from #start onward
    try:
        pdb.set_trace()                # reload readline; _modules_by_index_set may
                                       # fail under OOM -> PyMapping_DelItem cleanup
                                       # -> _Py_CheckSlotResult fatal (debug builds)
    except BaseException:
        pass
    finally:
        _testcapi.remove_mem_hooks()

print("no crash (state-dependent; use the vehicle source.py for a deterministic abort)",
      file=sys.stderr)
