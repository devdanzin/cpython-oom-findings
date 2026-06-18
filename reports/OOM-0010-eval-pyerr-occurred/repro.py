"""
Minimal reproducer: abort on assert(_PyErr_Occurred(tstate)) in the eval loop's
error path (Python/generated_cases.c.h, LABEL(error)) under OOM.

Affected:   CPython 3.16.0a0 (main), commit 15d7406.
Crash:      SIGABRT, Python/generated_cases.c.h  (LABEL(error) in
            _PyEval_EvalFrameDefault)
              Assertion `_PyErr_Occurred(tstate)' failed.
            (This build reports line 13817; the fuzzer build reports 13106 --
            same construct, different generated line numbering.)
Requires:   a free-threaded DEBUG build exposing _testcapi.set_nomemory.
            On non-debug builds (NDEBUG) the assert is compiled out; the same
            condition is turned into a clean MemoryError and the process exits
            normally (rc 1), so only the debug build aborts.

Run:
    python repro.py
    # aborts (rc 134) on the FT debug+ASan build;
    # exits cleanly with MemoryError on ft_release / jit / upstream.

What happens
------------
The eval loop reaches its central LABEL(error) -- taken when an opcode (here a
CALL) returns an error result -- and the debug build asserts that a Python
exception is actually set:

    LABEL(error) {
        ...
        #ifdef NDEBUG
        if (!_PyErr_Occurred(tstate)) {            // release: synthesize one
            _PyErr_SetString(tstate, PyExc_SystemError,
                             "error return without exception set");
        }
        #else
        assert(_PyErr_Occurred(tstate));           // debug: abort
        #endif
        ...
    }

Under OOM the failing opcode is the CALL of the C-extension type
``_remote_debugging.RemoteUnwinder(...)`` evaluated inside
``profiling.sampling.sample._new_unwinder`` (sample.py:102). That constructor
returns an error to the eval loop WITHOUT leaving a live exception, so
_PyErr_Occurred(tstate) is false at LABEL(error) and the assert fires.

Confirmed with gdb on the crashing run: neither the Argument-Clinic wrapper
(_remote_debugging_RemoteUnwinder___init__) nor its impl is ever entered -- the
error originates in the type-call / object-creation path before tp_init runs.
``Objects/typeobject.c:type_call`` even documents the hazard at its top:
"type_call() ... can clear it (directly or indirectly) and so the caller loses
its exception". Under OOM an exception raised during construction is cleared (or
never set) before control returns to the eval loop, leaving the "error result,
no exception" state the assert is meant to catch.

This is a generic invariant: *any* callee that returns an error without setting
an exception under OOM trips the same assert. The fuzzer found 13 vehicles that
share this exact signature across several unrelated stdlib paths (RemoteUnwinder,
json.load, subprocess._args_from_interpreter_flags, mimetypes._default_mime_types,
profiling _sort_to_mode, builtins) -- see meta.json "notes" for the split.

Suggested fix
-------------
Make ``_remote_debugging.RemoteUnwinder`` construction always leave an exception
set on every error path under OOM (and audit the other listed callees the same
way): on each ``return -1`` / NULL-return, ensure ``PyErr_NoMemory()`` /
``PyErr_Occurred()`` holds before returning, and do not ``PyErr_Clear()`` a
pending MemoryError while bailing out. The eval-loop assert itself is correct --
it is reporting a real contract violation by the callee.
"""
import faulthandler
import _testcapi
import profiling.sampling.sample as sample

faulthandler.enable()

# Fail every allocation from #5 onward. The earlier allocations let
# dump_stack() build the SampleProfiler and reach the RemoteUnwinder(...) call;
# allocation #5 then fails inside that C constructor, which returns an error to
# the eval loop without a live exception -> LABEL(error) assert -> SIGABRT.
_testcapi.set_nomemory(5, 0)
try:
    sample.dump_stack(-5)   # SampleProfiler.__init__ -> _new_unwinder -> RemoteUnwinder(...)
finally:
    _testcapi.remove_mem_hooks()
