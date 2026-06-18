"""
Minimal reproducer: abort on assert(debug_check_sanity(interp, code)) in
get_tools_for_instruction() (Python/instrumentation.c:1106) when applying
sys.monitoring instrumentation fails partway under OOM.

Affected:   CPython 3.16.0a0 (main, commit 15d7406), all builds.
Crash:      - FT debug+ASan / JIT (debug):  SIGABRT
                Python/instrumentation.c:1106
                Assertion `debug_check_sanity(interp, code)' failed.
              - FT release / upstream (NDEBUG): SIGSEGV at instrumentation.c:1119
                (NULL/partial code->_co_monitoring dereferenced). The assert is
                compiled out but the same inconsistent state is a real memory
                -safety bug, not a debug-only artifact.
Requires:   a build exposing _testcapi.set_nomemory (debug builds; the release
            builds segfault on the same script even without the assert).

Run:
    python repro.py        # rc 134 (abort) on debug builds; rc 139 (segv) on release.

Backtrace (gdb, FT debug):
    #8  get_tools_for_instruction   Python/instrumentation.c:1106  (assert debug_check_sanity)
    #9  call_instrumentation_vector  Python/instrumentation.c:1189
    #10 _Py_call_instrumentation_arg Python/instrumentation.c:1250
    #11 do_monitor_exc               Python/ceval.h:350   (MonitorRaise on the in-flight MemoryError)
    #12 _PyEval_EvalFrameDefault     Python/generated_cases.c.h:13839

Root cause (Python/instrumentation.c):

    Registering a global monitoring tool (sys.settrace / sys.setprofile /
    sys._settraceallthreads / sys.monitoring / profile.run) bumps the global
    instrumentation version (set_global_version, L1042) and mutates
    interp->monitors *first*, then walks executing code objects to apply the
    new instrumentation via instrument_all_executing_code_objects ->
    instrument_lock_held -> force_instrument_lock_held (L1805).

    force_instrument_lock_held calls update_instrumentation_data (L1700), which
    does several unchecked-for-rollback PyMem_Malloc allocations (the per-code
    tools/lines/per_instruction arrays, L1723/L1759/L1768/L1778/L1791, and the
    _co_monitoring struct itself in allocate_instrumentation_data, L1682). Under
    OOM one of these fails and the function returns -1 *before* reaching the
    `done:` label (L1925) that stores the new global_version into
    code->_co_instrumentation_version.

    The -1 propagates out as MemoryError, but the already-bumped global version
    and already-mutated interp->monitors are NOT rolled back. The code object is
    left out of sync: its _co_instrumentation_version / active_monitors no
    longer match the (now newer) global state, and its _co_monitoring may be
    NULL or only partially built.

    The very next monitored event -- here the RAISE event for the in-flight
    MemoryError, dispatched by _PyEval_MonitorRaise -> do_monitor_exc
    (ceval.h:350) -- reaches get_tools_for_instruction(), whose
    debug_check_sanity() assert (L1106) fails. On NDEBUG builds the assert is
    gone and L1119 instead reads code->_co_monitoring->active_monitors on a
    NULL/partial pointer -> SIGSEGV.

The OOM sweep is needed so that earlier allocations succeed (instrumentation
starts) while a later allocation inside update_instrumentation_data fails. The
trace function must stay registered so a subsequent event observes the stale
code object. Observed crash at start=9 on the FT debug build.

Likely fix: make instrumentation application transactional -- on any failure in
force_instrument_lock_held / update_instrumentation_data, restore the previous
global monitoring version and interp->monitors (or defer the global-version bump
until all code objects have been successfully re-instrumented) so no code object
is ever left out of sync with the global state.
"""
import sys
import _testcapi
import faulthandler

faulthandler.enable()


def tracer(frame, event, arg):
    return tracer


# Dense OOM sweep, fusil-style: fail every allocation from #start onward.
# sys.settrace() registers a global monitoring tool -> bumps the global
# instrumentation version and re-instruments executing code objects. When a
# PyMem_Malloc inside update_instrumentation_data fails, force_instrument_lock_held
# returns -1 before storing the new _co_instrumentation_version, yet the bumped
# global version / monitors are not rolled back. The next monitored event
# (the RAISE for the injected MemoryError) then trips debug_check_sanity.
for start in range(250):
    _testcapi.set_nomemory(start, 0)
    try:
        try:
            sys.settrace(tracer)   # crashes around start=9 on the FT debug build
        finally:
            _testcapi.remove_mem_hooks()
    except MemoryError:
        pass
