# Title

Abort: `assert(_PyErr_Occurred(tstate))` at `LABEL(error)` in `_PyEval_EvalFrameDefault` (`Python/generated_cases.c.h`) when a C-extension constructor (`_remote_debugging.RemoteUnwinder`) returns an error without an exception set under MemoryError

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report

The bytecode interpreter's central `error` label is taken whenever an opcode returns an error result. On debug builds it asserts the caller actually left a Python exception (`assert(_PyErr_Occurred(tstate))`); on release builds the same condition is converted into `SystemError: "error return without exception set"`. Under OOM, the `CALL` of the C-extension type `_remote_debugging.RemoteUnwinder(...)` -- evaluated inside `profiling.sampling.sample._new_unwinder` (`sample.py:102`) -- returns an error to the eval loop **without a live exception**, so `_PyErr_Occurred(tstate)` is false and the interpreter aborts.

## Reproducer

```python
import faulthandler, _testcapi
import profiling.sampling.sample as sample
faulthandler.enable()
_testcapi.set_nomemory(5, 0)   # fail every allocation from #5 onward
try:
    sample.dump_stack(-5)      # __init__ -> _new_unwinder -> RemoteUnwinder(...) errors w/o exc
finally:
    _testcapi.remove_mem_hooks()
```

Deterministic at `start=5` on the free-threaded debug+ASan build. `dump_stack(-5)` is just a convenient driver: `SampleProfiler.__init__` (`sample.py:87`) calls `_new_unwinder` (`sample.py:102`), which constructs `_remote_debugging.RemoteUnwinder`; allocation #5 fails inside that constructor.

## Backtrace

```
#8  _PyEval_EvalFrameDefault       Python/generated_cases.c.h:13817   <- LABEL(error): assert(_PyErr_Occurred(tstate))
#10 _PyEval_Vector                 Python/ceval.c:2141                 (running _new_unwinder, sample.py:102)
#13 call_method                    Objects/typeobject.c:3100
#14 slot_tp_init                   Objects/typeobject.c:11174          (SampleProfiler.__init__, Python)
#15 type_call                      Objects/typeobject.c:2484           (SampleProfiler(...) )
```

The faulting object is not a bad pointer: it is the **absence** of an exception. The eval loop holds an error *result* (the `RemoteUnwinder(...)` CALL returned NULL) but `tstate->current_exception` is NULL.

`13817` is this debug build's `generated_cases.c.h`; the catalog signature line `13106` is the build that produced the fuzzer stdout. Same construct -- the eval loop's `LABEL(error)`.

## Root cause

`Python/generated_cases.c.h`, `LABEL(error)` in `_PyEval_EvalFrameDefault`:

```c
LABEL(error) {
    _PyFrame_StackAssertInvalid(frame);
    #ifdef NDEBUG
    if (!_PyErr_Occurred(tstate)) {
        _PyErr_SetString(tstate, PyExc_SystemError,
                         "error return without exception set");
    }
    #else
    assert(_PyErr_Occurred(tstate));   /* <- aborts here */
    #endif
    ...
}
```

The assert is *correct*: it enforces the C-API contract that an error result must be accompanied by a live exception. The defect is in the callee. The CALL at `sample.py:102` invokes `_remote_debugging.RemoteUnwinder(...)`; under OOM that returns an error to the eval loop with no exception set.

Confirmed with gdb on the crashing run: neither the Argument-Clinic wrapper `_remote_debugging_RemoteUnwinder___init__` nor its impl `_remote_debugging_RemoteUnwinder___init___impl` is ever entered, so the error originates in the **type-call / object-creation path before `tp_init` runs**. `Objects/typeobject.c:type_call` documents exactly this hazard at its top:

```c
/* type_call() ... can clear it (directly or indirectly) and so the
   caller loses its exception */
assert(!_PyErr_Occurred(tstate));
```

Under OOM an exception that should accompany the construction failure is either never set or cleared before control returns to the eval loop, leaving the precise "error result, no exception" state the eval-loop assert is meant to catch.

This is a generic invariant violation: *any* callee that, under OOM, returns an error without setting an exception trips the identical assert. The fuzzer surfaced 13 vehicles with this exact signature across unrelated stdlib paths (see Notes) -- they are siblings sharing one signature, not one bug.

## Suggested fix

Audit the OOM error paths of the implicated C constructor(s) so an exception is always live on the way out. For `_remote_debugging.RemoteUnwinder`, ensure every `return -1` / NULL-return sets `PyErr_NoMemory()` (or otherwise leaves `PyErr_Occurred()` true) and never `PyErr_Clear()`s a pending `MemoryError` while bailing. The eval-loop assert should remain as-is -- it is correctly reporting a contract violation. (Hardening the eval loop to always synthesize a `SystemError` even on debug builds would only paper over the real callee bug.)

## Notes

Found by OOM-injection fuzzing (`set_nomemory`). This is an **assert-based abort on the FT debug build only**; the FT release, JIT, and upstream builds compile the `assert` out and instead surface a clean `MemoryError` (exit rc 1) -- they do **not** segfault. Per the OOM-catalog convention for assert-based aborts, the non-debug builds are recorded as `n/a`.

**Signature-cluster split (important).** The catalog signature for this cluster is the generic eval-loop `error`-label assert (`generated_cases.c.h:13106` / `error return without exception set`). 13 fuzzer vehicles match it, but they fall into several distinct underlying "error-without-exception" sites, grouped by Python frame:

- `_remote_debugging.RemoteUnwinder` via `profiling.sampling.sample._new_unwinder` -- **this report's representative** (`python-4/profiling_sampling_sample`, `python-5/profiling_sampling_sample`).
- `profiling.sampling` `_sort_to_mode` (`python-5/profiling_sampling_cli`, `python-7/profiling_sampling_cli`).
- `subprocess._args_from_interpreter_flags` via `multiprocessing.spawn` / `multiprocessing.util` (`python-5` x2, `python-7` x3).
- `mimetypes._default_mime_types` (`python-5/mimetypes` x2).
- `json.load` (`python-7/json`).
- `builtins` (`python-7/builtins`).

All 13 are listed as vehicles because they share the catalog signature, but the fix must address each callee's OOM error path; the representative root-caused above is the `RemoteUnwinder` constructor.

## Versions

- main (3.16.0a0, commit 15d7406); aborts on the free-threaded debug+ASan build at `start=5`. FT release / JIT / upstream builds: assert compiled out, condition surfaces as `MemoryError` (`n/a`).
