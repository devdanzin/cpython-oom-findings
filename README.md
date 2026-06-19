# cpython-oom-findings

Triage and reporting for CPython crashes found by **fusil** OOM-injection fuzzing
(`_testcapi.set_nomemory`) of CPython 3.16.0a0. Findings are published as **gists**
and tracked from a single **umbrella issue** (modelled on python/cpython#146102),
so developers can pick work without polluting the issue tracker with reports that
may not be actionable.

**State: 35 unique bugs (OOM-0001..0035), all with a minimal reproducer.** Discovery,
triage and minimization are done; publishing is the remaining (gated) work — see
`reports/NEXT_STEPS.md`. **`CLAUDE.md` is the operational hub** (workflow, dedup-key
rules, build matrix, lessons); `docs/MINIMIZATION.md` and `docs/DEDUP_PIPELINE.md` go
deep on those two areas.

## Layout

```
reports/OOM-####-<slug>/    one per UNIQUE bug (source of truth)
    report.md               the gist body (issue draft)
    repro.py                minimal, stdlib-only reproducer
    backtrace.txt           authoritative gdb backtrace
    meta.json               status, signature, vehicles, build matrix, gist URL, ...
catalog/backtraces/         every backtrace ever seen (dedupe corpus, kept forever)
scripts/                    signature.py · dedupe.py · gen_index.py · triage_matrix.sh
docs/SUBAGENT_BRIEF.md      the per-crash triage procedure
INDEX.md                    generated umbrella table (do not hand-edit)
```

**One row = one bug.** Crash directories are *vehicles*; many dedupe to the same
underlying CPython defect (e.g. 8 stdlib modules → one `_warnings.c` bug). Vehicles
are listed in each report's `meta.json`.

## Dedupe

Compare crashes by the **faulting frame** (the crash SITE), never by the directory's
signal label (assert-on-debug and segv-on-release can be the same bug) nor the ASan
re-raise pc. The current pipeline is a **single-writer read-only snapshot**: triage
writes `reports/*/meta.json`; `scripts/gen_known_sites.py` derives the flat
`catalog/known_sites.tsv`; the fuzzer dedupes in-loop against it and `scripts/ingest.py`
reconciles batches of run-dirs — see `docs/DEDUP_PIPELINE.md`. Detector/plumbing frames
(the assert machinery, `refcount.h` macros) must never be discriminating keys — see the
dedup-key rule in `CLAUDE.md`. (`scripts/signature.py`/`dedupe.py` are the earlier
single-crash matchers, still present.) Build matrix + exit-code reading: `CLAUDE.md` /
`scripts/triage_matrix.sh`.

## Workflow

1. Ingest a crash dir → `triage_matrix.sh` → backtrace + matrix results.
2. `dedupe.py` → existing vehicle, or a new `OOM-####`.
3. For new bugs: minimize, root-cause, write the report (`docs/SUBAGENT_BRIEF.md`).
4. `gen_index.py` → regenerate `INDEX.md`.
5. **Gated, maintainer-confirmed:** publish gists (`gh gist create`, public) and
   write URLs back into `meta.json`; post/update the umbrella issue. *(publish/retest
   scripts are TODO.)*
6. Periodically re-run reproducers against updated interpreters to flip status to
   `fixed:<commit>`.

## Status / not-yet-built

- `scripts/publish_gists.py` (create/edit public gists, capture URLs) — TODO.
- `scripts/retest.py` (re-run repros vs latest builds, update `fixed` status) — TODO.
- Ingestion from the fuzzing host(s) into a staging area — TODO.

## Credit

Crashes found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode
(fusil originally by Victor Stinner). Triage and reports drafted with Claude Code;
reproducers machine-generated. Each report carries an `_AI Disclaimer:_` line.
