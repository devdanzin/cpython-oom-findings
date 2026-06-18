# Per-crash triage brief (for subagents)

You are triaging ONE crash directory from a fusil OOM-fuzzing run (each has
`source.py`, `stdout`, `session.log`, `replay.py`). Goal: turn it into a clean,
deduped finding. Do **not** publish gists or open issues — produce files only.

## Steps

1. **Reproduce + backtrace.** Run `scripts/triage_matrix.sh <crash-dir>/source.py /tmp/<id>.bt`.
   Record which builds crash (the matrix dict) and capture the gdb backtrace.
   - If it exits cleanly on all builds (e.g. `ModuleNotFoundError`, plain exit 0), it is a
     **false alarm / environmental** — record that and stop.
2. **Signature + dedupe.** `python scripts/dedupe.py /tmp/<id>.bt`.
   - MATCH → this dir is another *vehicle* of an existing bug: add its path to that report's
     `meta.json` "vehicles" and stop (no new report).
   - NEAR → inspect; decide same-bug vs sibling with the maintainer/reviewer.
   - NEW → continue.
3. **Minimize.** Reduce to a stdlib-only reproducer: the `set_nomemory` sweep + the smallest
   call that triggers it. Confirm it still crashes on ≥1 build; note the crashing `start`.
   Watch for vehicle-only artifacts (e.g. a stdlib path gated on an interpreter flag — see the
   `context_aware_warnings` case; the underlying C bug is usually build-agnostic).
4. **Root-cause.** Read the CPython source at the faulting frame. State the defect in 1–3
   sentences (what allocation fails, what NULL/freed pointer is then used) and a suggested fix.
5. **Emit the report** under `reports/OOM-####-<slug>/`: `report.md`, `repro.py`,
   `backtrace.txt`, `meta.json` (schema below). Then run `python scripts/gen_index.py`.

## report.md template

```
# Title
<Segfault/Abort: <Py_DECREF(NULL)|assert ...> in <func> (<file>) under <condition>>

_AI Disclaimer: this issue was drafted by Claude Code, which also generated the reduced reproducer._

## Crash report      — 1–2 sentences
## Reproducer        — minimal stdlib-only sweep
## Backtrace         — trimmed gdb frames (note faulting object: NULL vs freed)
## Root cause        — the unchecked alloc / bad pointer, with file:line
## Suggested fix      — concrete diff sketch
## Notes             — found via set_nomemory fuzzing; build matrix; sibling of gh-146080 if applicable
## Versions          — main (commit), which builds reproduce
```

## meta.json schema

`id, slug, title, description, crash_kind(segv|abort|fatal), sites[], signature{site_frame, top_frames[]}, vehicles[], matrix{build->result}, repro_start, upstream_reported, upstream_issue, gist_url, status, found_date, confirmed_commit, notes`

`status` lifecycle: `drafted` → `gisted` → (`filed` w/ `upstream_issue`) → `fixed:<commit>` | `dup:OOM-####` | `false_alarm`.
