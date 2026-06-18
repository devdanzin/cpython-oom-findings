# CPython OOM-injection findings (fusil)

Crashes found by allocation-failure fuzzing (`_testcapi.set_nomemory`) of CPython 3.16.0a0. Each row links to a self-contained report (gist) with a minimal reproducer, backtrace, root cause, and suggested fix.

**Pick anything to work on** — open a CPython issue if one doesn't exist, comment with the issue/PR, and the Status column will be updated. Reports are deduped by crash signature; one row = one underlying bug (vehicles listed in the report).

_7 unique bug(s). Generated 2026-06-18._

_Found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode (fusil originally by Victor Stinner). Reports drafted by Claude Code; reproducers machine-generated._

Status legend: `draft` (not yet filed) · `report` (gist published) · `#N` (issue open) · **FIXED** `commit` · `dup:OOM-####` · `false alarm`.


## Segfaults

| Report | Description | Builds | Status |
|---|---|---|---|
| [OOM-0001](reports/OOM-0001-warnings-setup-context/report.md) | `_warnings.c`: NULL `filename` Py_DECREF in warnings setup/teardown under OOM (unchecked `PyUnicode_FromString("<sys>")`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0002](reports/OOM-0002-contextvar-set/report.md) | `Python/context.c`: unchecked `token_new()` NULL -> `Py_DECREF(tok)` on the `contextvar_set()` failure path under OOM | ft_debug_asan,ft_release,jit,upstream | draft |

## Assertion / abort

| Report | Description | Builds | Status |
|---|---|---|---|
| [OOM-0003](reports/OOM-0003-code-dealloc-unique-id/report.md) | `Objects/codeobject.c`: `_co_unique_id` is left uninitialized when `init_code()` fails under OOM (it is only assigned after success in `_PyCode_New`), so `code_dealloc`'s free-threaded assert fires on garbage and aborts | ft_debug_asan | draft |
| [OOM-0004](reports/OOM-0004-clear-freelist/report.md) | `Objects/object.c`: per-PyThreadState object freelist `size` desyncs from its chain under OOM. GC's clear_freelist asserts `size==0||-1` (debug abort); the sibling surface is PyList_New popping a corrupted `lists` node with a dangling ob_item that free_list_items then frees (use-after-free SEGV). Root: PyList_New (listobject.c:248) pops a freelist list before the fallible list_allocate_array, and on OOM Py_DECREF(op) pushes it back, churning the freelist accounting. | ft_debug_asan | draft |
| [OOM-0005](reports/OOM-0005-negative-refcount-stackref/report.md) | Eval-loop exit_unwind clears a frame's operand stack via _PyFrame_ClearLocals; under OOM an opcode error path left a stale/already-dead _PyStackRef on the value stack, so PyStackRef_XCLOSE->Py_DECREF underflows the object's refcount (debug: negative-refcount abort; release: use-after-free segv). Over-decref'd object is a MemoryError. | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0006](reports/OOM-0006-dictiter-gc-untrack/report.md) | `Objects/dictobject.c`: `dictiter_new()` Py_DECREF's a not-yet-GC-tracked `dict_itemiterator` when `_PyTuple_FromPairSteal(di_result)` fails under OOM; `dictiter_dealloc` then `_PyObject_GC_UNTRACK`s an untracked object | ft_debug_asan,jit,upstream | draft |

## Fatal Python error

| Report | Description | Builds | Status |
|---|---|---|---|
| [OOM-0007](reports/OOM-0007-context-dealloc-clears-exc/report.md) | `Python/context.c` `context_tp_dealloc` runs `PyObject_ClearWeakRefs` + `context_tp_clear` (HAMT/value decrefs) without saving/restoring `tstate->current_exception`; under OOM a Context is freed with a MemoryError in flight, the teardown clears it, and the gh-89373 `_Py_Dealloc` debug invariant fatals. | ft_debug_asan,jit | draft |
