# CPython OOM-injection findings (fusil)

Crashes found by allocation-failure fuzzing (`_testcapi.set_nomemory`) of CPython 3.16.0a0. Each row links to a self-contained report (gist) with a minimal reproducer, backtrace, root cause, and suggested fix.

**Pick anything to work on** — open a CPython issue if one doesn't exist, comment with the issue/PR, and the Status column will be updated. Reports are deduped by crash signature; one row = one underlying bug (vehicles listed in the report).

_35 unique bug(s). Generated 2026-06-19._

_Found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode (fusil originally by Victor Stinner). Reports drafted by Claude Code; reproducers machine-generated._

Status legend: `draft` (not yet filed) · `report` (gist published) · `#N` (issue open) · **FIXED** `commit` · `dup:OOM-####` · `false alarm`.


## Segfaults

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0001](reports/OOM-0001-warnings-setup-context/report.md) | Segfault: `Py_DECREF` of a NULL `filename` in `do_warn` (`_warnings.c:1139`) | ft_debug_asan,ft_release,jit,upstream | [#151673](https://github.com/python/cpython/issues/151673) |
| [OOM-0002](reports/OOM-0002-contextvar-set/report.md) | Segfault: `Py_DECREF(NULL)` in `PyContextVar_Set` (`context.c:367`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0024](reports/OOM-0024-templateiter-uninit-dealloc/report.md) | Segfault: dealloc of uninitialized iterator in `template_iter` (`templateobject.c:232`) | ft_debug_asan,jit | draft |
| [OOM-0028](reports/OOM-0028-normpath-encodefs-null/report.md) | Segfault: NULL deref in `os__path_normpath_impl` (`posixmodule.c:6149`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0031](reports/OOM-0031-excinfo-clear-type-segv/report.md) | Segfault: NULL `info` deref in `_excinfo_clear_type` (`crossinterp.c:1319`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0033](reports/OOM-0033-import-syspath-oom-over-decref/report.md) | Segfault / negative-refcount: over-decreffed `sys.path` entry in `PyType_IsSubtype` (`typeobject.c:2931`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0034](reports/OOM-0034-pegen-byte-offset-asutf8-null/report.md) | Segfault: unchecked `PyUnicode_AsUTF8` NULL deref in `pegen.c:33` | ft_debug_asan,ft_release,jit,upstream | draft |

## Assertion / abort

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0003](reports/OOM-0003-code-dealloc-unique-id/report.md) | Abort: uninitialized `_co_unique_id` assert in `code_dealloc` (`codeobject.c:2440`) | ft_debug_asan | draft |
| [OOM-0004](reports/OOM-0004-clear-freelist/report.md) | Abort/Segfault: corrupted object freelist in `clear_freelist` (`object.c:909`) | ft_debug_asan | draft |
| [OOM-0005](reports/OOM-0005-negative-refcount-stackref/report.md) | Abort: negative-refcount over-decref in `_PyFrame_ClearLocals` (`frame.c:101`) | ft_debug_asan | draft |
| [OOM-0006](reports/OOM-0006-dictiter-gc-untrack/report.md) | Abort/Segfault: `_PyObject_GC_UNTRACK` assert on untracked iterator in `dictiter_dealloc` (`dictobject.c:5532`) | ft_debug_asan,jit,upstream | draft |
| [OOM-0008](reports/OOM-0008-typeobject-lookup-pyerr/report.md) | Abort: `assert(!PyErr_Occurred())` in `_PyType_LookupStackRefAndVersion` (`typeobject.c:6343`) | ft_debug_asan,jit | draft |
| [OOM-0009](reports/OOM-0009-unicode-replace/report.md) | Abort: stale `release1` flag trips an ownership assert in `replace` (`unicodeobject.c:10783`) | ft_debug_asan,jit | draft |
| [OOM-0010](reports/OOM-0010-eval-pyerr-occurred/report.md) | Abort: `assert(_PyErr_Occurred(tstate))` in `_PyEval_EvalFrameDefault` (`generated_cases.c.h:13817`) | ft_debug_asan | draft |
| [OOM-0011](reports/OOM-0011-specialize-pyerr/report.md) | Abort: `assert(!PyErr_Occurred())` in `specialize` (`specialize.c:364`) | ft_debug_asan,jit | draft |
| [OOM-0012](reports/OOM-0012-instrumentation-sanity/report.md) | Abort/Segfault: stale instrumentation in `get_tools_for_instruction` (`instrumentation.c:1106`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0013](reports/OOM-0013-ceval-843/report.md) | Abort: builtin breaks result/error contract in `_Py_BuiltinCallFastWithKeywords_StackRef` (`ceval.c:843`) | ft_debug_asan,jit | draft |
| [OOM-0014](reports/OOM-0014-interpchannels-3487/report.md) | Abort/Segfault: unchecked NULL in `channelsmod__channel_id` (`_interpchannelsmodule.c:3487`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0015](reports/OOM-0015-cfunction-check-kwargs/report.md) | Abort: stale exception in `cfunction_check_kwargs` (`methodobject.c:409`) | ft_debug_asan,jit | draft |
| [OOM-0016](reports/OOM-0016-interpqueues-queue-clear/report.md) | Abort: `assert(!queue->alive)` in `_queue_clear` (`_interpqueuesmodule.c:559`) | ft_debug_asan,jit | draft |
| [OOM-0017](reports/OOM-0017-gc-free-threading-1116/report.md) | Abort: negative `gc_refs` ("refcount too small") in `validate_gc_objects` (`gc_free_threading.c:1116`) | ft_debug_asan,jit | draft |
| [OOM-0018](reports/OOM-0018-dictobject-205/report.md) | Abort: ownership assert in `set_keys` (`dictobject.c:205`) | ft_debug_asan | draft |
| [OOM-0019](reports/OOM-0019-refcount-520/report.md) | Abort: double-free in `_PyPegen_raise_error_known_location` (`pegen_errors.c:363`) | ft_debug_asan,jit | draft |
| [OOM-0025](reports/OOM-0025-unspecialize-pending-exc/report.md) | Abort: `assert(!PyErr_Occurred())` in `unspecialize` (`specialize.c:378`) | ft_debug_asan,jit | draft |
| [OOM-0026](reports/OOM-0026-interpchannels-error-desync/report.md) | Abort: err-code vs `PyErr` desync in `handle_channel_error` (`_interpchannelsmodule.c:398` / `:443`) | ft_debug_asan,jit | draft |
| [OOM-0027](reports/OOM-0027-pop-jump-boolcheck/report.md) | Abort: `assert(PyStackRef_BoolCheck(cond))` in `POP_JUMP_IF_FALSE` (`generated_cases.c.h:11120`) | ft_debug_asan,jit | draft |
| [OOM-0029](reports/OOM-0029-neg-refcount-memoryerror-oom/report.md) | Abort: negative refcount on a `MemoryError` (`tuple_dealloc`, `tupleobject.c:277`) | ft_debug_asan,jit | draft |
| [OOM-0030](reports/OOM-0030-unicode-subtype-new-null-data/report.md) | Abort: `Py_DECREF` of NULL-data unicode in `unicode_subtype_new` (`unicodeobject.c:13986`) | ft_debug_asan,jit | draft |
| [OOM-0032](reports/OOM-0032-warn-explicit-pending-exc/report.md) | Abort: pending-exception assert from `warn_explicit` normalization (`_warnings.c:799/806`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0035](reports/OOM-0035-stringio-getvalue-oom-bad-maxchar/report.md) | Abort / malformed str: invalid `maxchar` in `_PyUnicode_FromUCS4` (`unicodeobject.c:2228`) | ft_debug_asan,ft_release,jit,upstream | draft |

## Fatal Python error

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0007](reports/OOM-0007-context-dealloc-clears-exc/report.md) | Fatal: `context_tp_dealloc` clears the pending exception (`context.c:535`) | ft_debug_asan,jit | draft |
| [OOM-0020](reports/OOM-0020-mem-debug-rawfree-badid/report.md) | Fatal: `_PyMem_DebugRawFree: bad ID` in `free_threadstate` (`pystate.c:1527`) | ft_debug_asan,ft_release | draft |
| [OOM-0021](reports/OOM-0021-checkfunctionresult-null/report.md) | Fatal: NULL returned without an exception set in `_Py_CheckFunctionResult` (`call.c:43`) | ft_debug_asan,jit | draft |
| [OOM-0022](reports/OOM-0022-checkslotresult/report.md) | Fatal: stale `MemoryError` trips `_Py_CheckSlotResult` in `reload_singlephase_extension` (`import.c:2011`) | ft_debug_asan,jit | draft |
| [OOM-0023](reports/OOM-0023-dealloc-clears-exc-family/report.md) | Fatal: dealloc clears the in-flight exception in `subtype_dealloc` (`typeobject.c:2719`) | ft_debug_asan,jit | draft |
