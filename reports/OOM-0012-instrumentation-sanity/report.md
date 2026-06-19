# Abort/Segfault: stale instrumentation in `get_tools_for_instruction` (`instrumentation.c:1106`)

*Registering a global monitoring tool bumps the interpreter's instrumentation version, but an alloc failure in `update_instrumentation_data()` returns `-1` without rolling it back, leaving a code object's version stale and `_co_monitoring` NULL/partial; the next monitored event trips `debug_check_sanity()` (abort on debug, segfault at `instrumentation.c:1119` on release).*

_AI Disclaimer: this gist was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

Registering a global monitoring tool (`sys.settrace` / `sys.setprofile` / `sys._settraceallthreads` / `sys.monitoring` / `profile.run`) bumps the global instrumentation version and mutates `interp->monitors` *before* re-instrumenting executing code objects. If an allocation inside `update_instrumentation_data()` fails under OOM, `force_instrument_lock_held()` returns `-1` before storing the new version into the code object, and the bumped global state is **not** rolled back. The code object is left out of sync; the next monitored event (the `RAISE` for the in-flight `MemoryError`) reaches `get_tools_for_instruction()` whose `debug_check_sanity()` assert fires and aborts. On non-debug builds the assert is compiled out and the same inconsistency instead dereferences a NULL/partial `_co_monitoring` and **segfaults** at `instrumentation.c:1119`.

## Reproducer

```python
import sys, _testcapi, faulthandler
faulthandler.enable()

def tracer(frame, event, arg):
    return tracer

# Fail every allocation from #start onward; settrace bumps the global
# instrumentation version then re-instruments code objects -- an alloc failure
# inside update_instrumentation_data leaves a code object out of sync.
for start in range(250):
    _testcapi.set_nomemory(start, 0)
    try:
        try:
            sys.settrace(tracer)
        finally:
            _testcapi.remove_mem_hooks()
    except MemoryError:
        pass
```

Deterministic, crashing at `start=9` on the free-threaded debug+ASan build. `sys.settrace` is just a convenient driver for `_Py_Instrument`; any global-monitoring registration (`setprofile`, `_settraceallthreads`, PEP 669 `sys.monitoring`, `profile.run`) reaches the same code.

## Backtrace

```
#8  get_tools_for_instruction   Python/instrumentation.c:1106  <- assert(debug_check_sanity(interp, code))
#9  call_instrumentation_vector  Python/instrumentation.c:1189
#10 _Py_call_instrumentation_arg Python/instrumentation.c:1250
#11 do_monitor_exc               Python/ceval.h:350             (MonitorRaise on the in-flight MemoryError)
#12 _PyEval_EvalFrameDefault     Python/generated_cases.c.h:13839
```

Release / upstream build, same script, assert compiled out:

```
#0  get_tools_for_instruction   Python/instrumentation.c:1119  <- SIGSEGV: code->_co_monitoring NULL/partial
#1  call_instrumentation_vector  Python/instrumentation.c:1189
#3  do_monitor_exc               Python/ceval.h:350
#4  _PyEval_MonitorRaise         Python/ceval.c:2429
```

## Root cause

`Python/instrumentation.c`. Tool registration bumps the global version *first*:

```c
set_global_version(_PyThreadState_GET(), version);          /* L1042/L2142: interp->monitors + version mutated */
int res = instrument_all_executing_code_objects(interp);    /* L1146: then walk code objects */
```

`instrument_all_executing_code_objects()` (L1969) calls `instrument_lock_held()` -> `force_instrument_lock_held()` (L1805), which calls `update_instrumentation_data()` (L1700). That function performs several allocations with no rollback of the global state on failure:

```c
/* allocate_instrumentation_data, L1682 */
_PyCoMonitoringData *monitoring = PyMem_Malloc(sizeof(_PyCoMonitoringData));
if (monitoring == NULL) { PyErr_NoMemory(); return -1; }
...
/* update_instrumentation_data: tools / lines / line_tools / per_instruction arrays */
code->_co_monitoring->tools = PyMem_Malloc(code_len);          /* L1723 */
... lines = PyMem_Malloc(...);                                  /* L1759 */
... per_instruction_opcodes = PyMem_Malloc(...);                /* L1778, etc. */
if (... == NULL) { PyErr_NoMemory(); return -1; }
```

When any of these fails under OOM, control returns `-1` and unwinds back through `force_instrument_lock_held()` **before** its `done:` label (L1925) runs:

```c
done:
    FT_ATOMIC_STORE_UINTPTR_RELEASE(code->_co_instrumentation_version,
                                    global_version(interp));    /* L1926: never reached on the failing object */
```

So `code->_co_instrumentation_version` stays at the *old* value while `global_version(interp)` is now newer, and `code->_co_monitoring` is NULL or only partially built. The `-1` surfaces to Python as `MemoryError`, but `set_global_version` / `interp->monitors` are left mutated. The next monitored event on that code object -- the `RAISE` for the injected `MemoryError`, via `_PyEval_MonitorRaise` -> `do_monitor_exc` (`ceval.h:350`) -- calls `get_tools_for_instruction()`, whose `debug_check_sanity()` (L1082) checks `is_version_up_to_date() && instrumentation_cross_checks()`; both now fail, so the assert at L1106 aborts. Under `NDEBUG` the assert is gone and L1119 reads `code->_co_monitoring->active_monitors.tools[event]` on the NULL/partial pointer -> SIGSEGV.

## Suggested fix

Make instrumentation application transactional with respect to the global version. Either (a) defer the `set_global_version()` bump until `instrument_all_executing_code_objects()` has successfully re-instrumented every code object (apply to all, then publish the version), or (b) on any failure in `force_instrument_lock_held()` / `update_instrumentation_data()`, restore the previous global monitoring version and `interp->monitors` before returning `-1`, so no code object is ever observed out of sync with the global state. As a defensive minimum, `get_tools_for_instruction()` (and L1119) should not assume `_co_monitoring != NULL` once an instrumentation update has failed.

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). **Not** a debug-only assert: this is a genuine, build-agnostic memory-safety bug. The `debug_check_sanity` assertion fires on the assertion-enabled builds (`ft_debug_asan`, `jit`), and the *same* inconsistent instrumentation state segfaults at `instrumentation.c:1119` on the non-debug builds (`ft_release`, `upstream`) where the assert is compiled out. All four builds crash on the minimal reproducer (abort on debug, segv on release).

Nine fuzzer vehicles abort at the identical `instrumentation.c:1106` assertion: the representative drives it via `sys._settraceallthreads` under the OOM sweep; the `profile-*` vehicles via `profile.run`/`runctx` (which install a PEP 669 / `setprofile` tool); and `threading-assertion-sigabrt` via thread-level tracing. All register a global monitoring tool under OOM and fail mid-`instrument_all_executing_code_objects`.

## Versions

- main (3.16.0a0, commit 15d7406). `ft_debug_asan`: abort (`instrumentation.c:1106`). `jit`: abort (same assert). `ft_release`: segfault (`instrumentation.c:1119`). `upstream`: segfault (same site). The defect reproduces on all four builds.
