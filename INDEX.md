# CPython OOM-injection findings (fusil)

Crashes found by allocation-failure fuzzing (`_testcapi.set_nomemory`) of CPython 3.16.0a0. Each row links to a self-contained report (gist) with a minimal reproducer, backtrace, root cause, and suggested fix.

**Pick anything to work on** — open a CPython issue if one doesn't exist, comment with the issue/PR, and the Status column will be updated. Reports are deduped by crash signature; one row = one underlying bug (vehicles listed in the report).

_2 unique bug(s). Generated 2026-06-18. Drafted with Claude Code; reproducers machine-generated._

Status legend: `draft` (not yet filed) · `report` (gist published) · `#N` (issue open) · **FIXED** `commit` · `dup:OOM-####` · `false alarm`.


## Segfaults

| Report | Description | Builds | Status |
|---|---|---|---|
| [OOM-0001](reports/OOM-0001-warnings-setup-context/report.md) | `_warnings.c`: NULL `filename` Py_DECREF in warnings setup/teardown under OOM (unchecked `PyUnicode_FromString("<sys>")`) | ft_debug_asan,ft_release,jit,upstream | draft |
| [OOM-0002](reports/OOM-0002-contextvar-set/report.md) | `Python/context.c`: unchecked `token_new()` NULL -> `Py_DECREF(tok)` on the `contextvar_set()` failure path under OOM | ft_debug_asan,ft_release,jit,upstream | draft |
