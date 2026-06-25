# CPython OOM-injection findings (fusil)

Crashes found by allocation-failure fuzzing (`_testcapi.set_nomemory`) of CPython 3.16.0a0. Each row links to a self-contained report (gist) with a minimal reproducer, backtrace, root cause, and suggested fix.

**Pick anything to work on** — open a CPython issue if one doesn't exist, comment with the issue/PR, and the Status column will be updated. Reports are deduped by crash signature; one row = one underlying bug (vehicles listed in the report).

_41 unique bug(s). Generated 2026-06-24._

_Found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode (fusil originally by Victor Stinner). Reports drafted by Claude Code; reproducers machine-generated._

Status legend: `draft` (not yet filed) · `report` (gist published) · `#N` (issue open) · **FIXED** `commit` · `dup:OOM-####` · `false alarm`.


## Segfaults

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0001](https://gist.github.com/devdanzin/464cef74ca8186843f33a38078476ac4) | Segfault: `Py_DECREF` of a NULL `filename` in `do_warn` (`_warnings.c:1139`) | ft_debug_asan,ft_release,jit,upstream | [#151673](https://github.com/python/cpython/issues/151673) |
| [OOM-0002](https://gist.github.com/devdanzin/2dfeabe7508f8e98f27f6df7e381f1cf) | Segfault: `Py_DECREF(NULL)` in `PyContextVar_Set` (`context.c:367`) | ft_debug_asan,ft_release,jit,upstream | **FIXED** |
| [OOM-0024](https://gist.github.com/devdanzin/acf15ad4117c6343b48ed8fdfe7ad167) | Segfault: dealloc of uninitialized iterator in `template_iter` (`templateobject.c:232`) | ft_debug_asan,jit | [#151815](https://github.com/python/cpython/issues/151815) |
| [OOM-0028](https://gist.github.com/devdanzin/774867b89b3de8d36d7e2ac405034577) | Segfault: NULL deref in `os__path_normpath_impl` (`posixmodule.c:6149`) | ft_debug_asan,ft_release,jit,upstream | **FIXED** |
| [OOM-0031](https://gist.github.com/devdanzin/44ffdf25538575e497fd80552ea5d467) | Segfault: NULL `info` deref in `_excinfo_clear_type` (`crossinterp.c:1319`) | ft_debug_asan,ft_release,jit,upstream | **FIXED** |
| [OOM-0033](https://gist.github.com/devdanzin/249032e1746d63406a5f68d7dfdedb79) | Segfault / negative-refcount: over-decreffed `sys.path` entry in `PyType_IsSubtype` (`typeobject.c:2931`) | ft_debug_asan,ft_release,jit,upstream | report |
| [OOM-0034](https://gist.github.com/devdanzin/9871a21facf4c9c6a415e220f9d10762) | Segfault: unchecked `PyUnicode_AsUTF8` NULL deref in `pegen.c:33` | ft_debug_asan,ft_release,jit,upstream | [#151798](https://github.com/python/cpython/issues/151798) |
| [OOM-0037](reports/OOM-0037-subinterp-unraisable-structseq/report.md) | Segfault: NULL `UnraisableHookArgs` type-dict deref in `PyStructSequence_New`/`make_unraisable_hook_args` during sub-interpreter finalization under OOM (`structseq.c:30`) | ft_debug_asan,gil_debug_asan,jit,ft_release,upstream | draft |
| [OOM-0040](reports/OOM-0040-extensions-cache-set-null-key/report.md) | SEGV: `_extensions_cache_set` hashes a NULL key under OOM (`hashtable_hash_str`, `import.c:1312`) | ft_debug_asan,ft_release,jit,upstream | draft |

## Assertion / abort

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0003](https://gist.github.com/devdanzin/b628c59722820b55c61a400a973771d5) | Abort: uninitialized `_co_unique_id` assert in `code_dealloc` (`codeobject.c:2440`) | ft_debug_asan | **FIXED** |
| [OOM-0004](https://gist.github.com/devdanzin/315e83b2da6a5809ce5ae1d748cdd0ae) | Abort/Segfault: corrupted object freelist in `clear_freelist` (`object.c:909`) | ft_debug_asan | report |
| [OOM-0005](https://gist.github.com/devdanzin/22b71f61343c81df5bea9b7fca798e87) | Abort: negative-refcount over-decref in `_PyFrame_ClearLocals` (`frame.c:101`) | ft_debug_asan | report |
| [OOM-0006](https://gist.github.com/devdanzin/c809eb4072c0c787c0c890f54ba1c843) | Abort/Segfault: `_PyObject_GC_UNTRACK` assert on untracked iterator in `dictiter_dealloc` (`dictobject.c:5532`) | ft_debug_asan,jit,upstream | [#152107](https://github.com/python/cpython/issues/152107) |
| [OOM-0008](https://gist.github.com/devdanzin/3c6690d0561acc62752a953e12b20197) | Abort: `assert(!PyErr_Occurred())` in `_PyType_LookupStackRefAndVersion` (`typeobject.c:6343`) | ft_debug_asan,jit | report |
| [OOM-0009](https://gist.github.com/devdanzin/34b633230f6d2301ba17dec195ffe4b7) | Abort: stale `release1` flag trips an ownership assert in `replace` (`unicodeobject.c:10783`) | ft_debug_asan,jit | report |
| [OOM-0010](https://gist.github.com/devdanzin/d3c1d06e95c006a320dbbfffcc210d52) | Abort: `assert(_PyErr_Occurred(tstate))` in `_PyEval_EvalFrameDefault` (`generated_cases.c.h:13817`) | ft_debug_asan | report |
| [OOM-0011](https://gist.github.com/devdanzin/892b61619c1b3c8c2018331b3f1f4983) | Abort: `assert(!PyErr_Occurred())` in `specialize` (`specialize.c:364`) | ft_debug_asan,jit | report |
| [OOM-0012](https://gist.github.com/devdanzin/610c147c8e2d42a576bab3c1c2713391) | Abort/Segfault: stale instrumentation in `get_tools_for_instruction` (`instrumentation.c:1106`) | ft_debug_asan,ft_release,jit,upstream | report |
| [OOM-0013](https://gist.github.com/devdanzin/1736971107bea3aa04ce19db21c90845) | Abort: builtin breaks result/error contract in `_Py_BuiltinCallFastWithKeywords_StackRef` (`ceval.c:843`) | ft_debug_asan,jit | [#151968](https://github.com/python/cpython/issues/151968) |
| [OOM-0014](https://gist.github.com/devdanzin/ceb4b16662d22b3dcb1b56cd8481c9e7) | Abort/Segfault: unchecked NULL in `channelsmod__channel_id` (`_interpchannelsmodule.c:3487`) | ft_debug_asan,ft_release,jit,upstream | [#151902](https://github.com/python/cpython/issues/151902) |
| [OOM-0015](https://gist.github.com/devdanzin/d40d39e6abfb746bd9d96de261205190) | Abort: stale exception in `cfunction_check_kwargs` (`methodobject.c:409`) | ft_debug_asan,jit | report |
| [OOM-0016](https://gist.github.com/devdanzin/05be8efe6b08c2b3ac3e2c17c784da0c) | Abort: `assert(!queue->alive)` in `_queue_clear` (`_interpqueuesmodule.c:559`) | ft_debug_asan,jit | [#152130](https://github.com/python/cpython/issues/152130) |
| [OOM-0017](https://gist.github.com/devdanzin/6e7a3a9487689e55d7dd4f70b1ce489f) | Abort: negative `gc_refs` ("refcount too small") in `validate_gc_objects` (`gc_free_threading.c:1116`) | ft_debug_asan,jit | report |
| [OOM-0018](https://gist.github.com/devdanzin/99b84915b197ae0ade7face262b8af66) | Abort: ownership assert in `set_keys` (`dictobject.c:205`) | ft_debug_asan | report |
| [OOM-0019](https://gist.github.com/devdanzin/9bd9423256ea03c08231d1ebe542db89) | Abort: double-free in `_PyPegen_raise_error_known_location` (`pegen_errors.c:363`) | ft_debug_asan,jit | [#151931](https://github.com/python/cpython/issues/151931) |
| [OOM-0025](https://gist.github.com/devdanzin/3aaffc18b68ca2ae5fffa72aa6cdb2ea) | Abort: `assert(!PyErr_Occurred())` in `unspecialize` (`specialize.c:378`) | ft_debug_asan,jit | report |
| [OOM-0026](https://gist.github.com/devdanzin/bf6f784d4bcd21acd471ea45b6f23c70) | Abort: err-code vs `PyErr` desync in `handle_channel_error` (`_interpchannelsmodule.c:398` / `:443`) | ft_debug_asan,jit | report |
| [OOM-0027](https://gist.github.com/devdanzin/d5c602c29ac3881290269b444d77db3c) | Abort: `assert(PyStackRef_BoolCheck(cond))` in `POP_JUMP_IF_FALSE` (`generated_cases.c.h:11120`) | ft_debug_asan,jit | report |
| [OOM-0029](https://gist.github.com/devdanzin/10e0fdaf3d89dbe394d94fbf765c70a1) | Abort: negative refcount on a `MemoryError` (`tuple_dealloc`, `tupleobject.c:277`) | ft_debug_asan,jit | report |
| [OOM-0030](https://gist.github.com/devdanzin/fbfb9d6cd5eeb518e4f9eeab44be3893) | Abort: `Py_DECREF` of NULL-data unicode in `unicode_subtype_new` (`unicodeobject.c:13986`) | ft_debug_asan,jit | report |
| [OOM-0032](https://gist.github.com/devdanzin/f7e483080647c7b76fbda79bfeb07e9c) | Abort: pending-exception assert from `warn_explicit` normalization (`_warnings.c:799/806`) | ft_debug_asan,ft_release,jit,upstream | report |
| [OOM-0035](https://gist.github.com/devdanzin/8c86ca358f3711740a692eaac730b527) | Abort / malformed str: invalid `maxchar` in `_PyUnicode_FromUCS4` (`unicodeobject.c:2228`) | ft_debug_asan,ft_release,jit,upstream | report |
| [OOM-0036](reports/OOM-0036-list-append-oom-double-free/report.md) | Double-free / use-after-free: `list.append(x)` under OOM double-frees the item (`_CALL_LIST_APPEND` steals `arg`, then `ERROR_NO_POP`) | ft_debug_asan,ft_release,jit,upstream | [#151818](https://github.com/python/cpython/issues/151818) |
| [OOM-0042](reports/OOM-0042-import-run-extension-stale-memoryerror/report.md) | Abort: stale `MemoryError` trips `assert(!PyErr_Occurred())` in `import_run_extension` (`import.c:2301`) | ft_debug_asan,jit | draft |

## Fatal Python error

| Report | Title | Crashing builds | Status |
|---|---|---|---|
| [OOM-0007](https://gist.github.com/devdanzin/bf9fec4554c58c2a279b05b7ff8e6d9b) | Fatal: `context_tp_dealloc` clears the pending exception (`context.c:535`) | ft_debug_asan,jit | [#152083](https://github.com/python/cpython/issues/152083) |
| [OOM-0020](https://gist.github.com/devdanzin/df523c79368baa0c44bd69e9d5ee0c7e) | Fatal: `_PyMem_DebugRawFree: bad ID` in `free_threadstate` (`pystate.c:1527`) | ft_debug_asan,ft_release | report |
| [OOM-0021](https://gist.github.com/devdanzin/e113c48a4e249ae7e4d1e42020db65c4) | Fatal: NULL returned without an exception set in `_Py_CheckFunctionResult` (`call.c:43`) | ft_debug_asan,jit | report |
| [OOM-0022](https://gist.github.com/devdanzin/0964a71a7038ee90137f11c2527aad3c) | Fatal: stale `MemoryError` trips `_Py_CheckSlotResult` in `reload_singlephase_extension` (`import.c:2011`) | ft_debug_asan,jit | report |
| [OOM-0023](https://gist.github.com/devdanzin/dc5123e50ea0402292e841411a294d3d) | Fatal: dealloc clears the in-flight exception in `subtype_dealloc` (`typeobject.c:2719`) | ft_debug_asan,jit | report |
| [OOM-0038](reports/OOM-0038-indexpool-tlbc-reserve-no-tstate/report.md) | Fatal/segv: `_PyIndexPool_AllocIndex` calls `PyErr_NoMemory()` with no active thread state while reserving a TLBC index during free-threaded sub-interpreter creation (`index_pool.c:167`) | ft_debug_asan,ft_release | draft |
| [OOM-0039](reports/OOM-0039-deque-clear-pyerr-clear/report.md) | Fatal: `deque_clear` clears the in-flight exception via its `newblock`-failure `PyErr_Clear()` (`_collectionsmodule.c:751`) | ft_debug_asan,jit | draft |
