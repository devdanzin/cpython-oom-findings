# cpython-oom-findings

A catalog of **memory-safety and assertion crashes in CPython** (`main`, 3.16.0a0),
found by driving allocation-failure (out-of-memory) error paths with the
[**fusil**](https://github.com/devdanzin/fusil) fuzzer. One directory per *unique* bug,
each with a minimal reproducer, a backtrace, a root-cause analysis, and a suggested fix.

The idea: when an allocation fails part-way through an operation, CPython's error/cleanup
paths are exercised in ways normal testing rarely reaches — and a program that dutifully
catches `MemoryError` can still be left with a use-after-free, a double-free, or a tripped
invariant. fusil makes those allocations fail (via `_testcapi.set_nomemory`); this repo
turns the resulting flood of crashes (≈96% duplicates) into a deduped, minimized,
root-caused set of reports.

## The findings

- **36 unique bugs** (`reports/OOM-0001` … `OOM-0036`), each with a deterministic,
  standard-library-only reproducer.
- **[INDEX.md](INDEX.md)** is the table — one row per bug (title, which builds crash,
  status), linking each to its report/gist.
- **OOM-0001 … OOM-0035** are published as gists and tracked from the umbrella issue
  **[python/cpython#151763](https://github.com/python/cpython/issues/151763)**.
- **OOM-0036** — a `list.append()` double-free under `MemoryError` (in the
  `_CALL_LIST_APPEND` bytecode), found by fusil's stateful-sequence mode and reproducible
  *without any test API* via a real `RLIMIT_AS` cap — is filed as
  **[python/cpython#151818](https://github.com/python/cpython/issues/151818)**.

## What's in each report

```
reports/OOM-####-<slug>/
    report.md       the analysis: crash report, reproducer, backtrace, root cause, fix
    repro.py        a minimal, deterministic, standard-library-only reproducer
    backtrace.txt   the authoritative gdb / ASan backtrace
    meta.json       structured metadata (sites, build matrix, status, …)
```

## Reproducing a bug

Most reproducers use `_testcapi.set_nomemory(...)` to fail allocations deterministically,
so they need a CPython built with `--with-pydebug` (which exposes `_testcapi`):

```bash
./python reports/OOM-0036-list-append-oom-double-free/repro.py
```

Debug builds abort on the tripped assertion; release builds may segfault or silently
corrupt (the per-report build matrix records which). Several reproduce on a **release**
build directly. OOM-0036 additionally ships a no-`_testcapi` reproducer (`repro_natural.py`)
that triggers the same bug under a real memory limit.

## How they were found

[fusil](https://github.com/devdanzin/fusil)'s OOM-injection modes — `--oom-fuzz` and the
newer `--oom-seq` stateful sequences. Crashes are deduped by their faulting **C site** (the
fuzzed module is just a vehicle), minimized with shrinkray, then root-caused against CPython
source. The dedup model and triage workflow are documented in [`CLAUDE.md`](CLAUDE.md).

## Picking one up

These are filed so they can be worked individually — comment on the umbrella issue
([#151763](https://github.com/python/cpython/issues/151763)) or the specific issue to claim
or fix one.

## Credit & a note on AI assistance

Crashes found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode (fusil
originally by Victor Stinner). The triage, the reduced reproducers, and the root-cause
write-ups were produced with **[Claude Code](https://claude.com/claude-code)** working
alongside the maintainer, who reviews and re-reproduces every finding before it's disclosed.
Each published gist/issue carries an explicit disclaimer.

## More

- [`INDEX.md`](INDEX.md) — the full table · [`catalog/SUMMARY.md`](catalog/SUMMARY.md) — snapshot
- [`CLAUDE.md`](CLAUDE.md) — operational hub (dedup model, build matrix, lifecycle)
- [`HANDOFF.md`](HANDOFF.md) / [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) — working on this from scratch
