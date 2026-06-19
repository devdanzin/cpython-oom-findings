# Dedupe pipeline: snapshot + ingest (single-writer, no shared mutable catalog)

Built for the local high-throughput campaign: many fuzzer instances generating crash
dirs faster than we can hand-triage. The pipeline dedupes the flood against the known-bug
catalog and surfaces **only genuinely-new crash sites** for a report.

## The concurrency design (why there's no lost-write problem)

`reports/*/meta.json` is the **single source of truth**, written only by triage. From it
we derive a flat **read-only snapshot** `catalog/known_sites.tsv`. Nothing else ever
writes the catalog, so there is no concurrent-write hazard at all:

- **Fuzzer instances only READ** the snapshot (load it at startup, dedupe their own
  crashers in-loop against it — that prunes the ~96% that are dups of already-known
  bugs). New-site crashers go to the instance's own output dir.
- A **single-writer merge** (`ingest.py`, run by triage) reconciles all instances'
  outputs, dedupes the rare cross-instance new-site collisions, and drafts reports;
  then `gen_known_sites.py` regenerates the snapshot.

The only thing that can race — two instances independently discovering the *same
brand-new* site in the same window — costs at most one duplicate dir, reconciled by the
merge. (If that ever matters, swap the snapshot for SQLite WAL + `UNIQUE(sig)` +
`INSERT OR IGNORE`; not built speculatively.)

## Tools

### `gen_known_sites.py` — regenerate the snapshot
```
python3 scripts/gen_known_sites.py     # reports/*/meta.json (+ backtrace.txt) -> catalog/known_sites.tsv
```
Emits keys per bug: `func` (`file:func`, stable across line drift), `line` (`file:line`,
near-matched within ±12), `assert` (`file:expr`, disambiguates same-function eval
asserts), `msg` (fatal-message prefix). Run it whenever the catalog changes — it also
**validates every `meta.json`** (the fastest catch for a malformed-JSON note).

**Key curation — generic detector/plumbing keys must never be discriminators.** The
deduper matches a crash against ALL keys and, on a tie, `decide()` picks the lowest id
(`sorted(matched)[0]`). So a key shared by several bugs mislabels a crash to the
lowest-numbered one. `gen_known_sites.py` therefore *skips* the generic catchers:

- `GENERIC_ASSERTS` — `!PyErr_Occurred()` / `!_PyErr_Occurred(tstate)` (the "no exception
  pending" invariant, asserted in many functions). Fixed the OOM-0011↔0025 mislabel.
- `GENERIC_DETECTOR_FUNCS` (`_Py_NegativeRefcount`, `_PyObject_AssertFailed`) +
  `DETECTOR_FILE` (`refcount`/`pyatomic*`/`object`.h inlined macros) + `_generic_assert()`
  (the `object has negative ref count` message) — the negrefcount/assert *detector*,
  shared by the whole negrefcount family. Fixed the OOM-0029↔0019 mislabel. Mirrors
  `oom_dedup._BT_SKIP` / `_BT_SKIP_FILE` so the snapshot and the live-backtrace resolver
  agree on what counts as a real site.

These detectors *catch* corruption; they are never the defect. The real discriminator is
the bug's own site (the dealloc cascade, the parser frame, the specific assert).
**After adding a bug, grep its keys and prune any generic/shared frame before committing.**

### `ingest.py` — dedupe a pile of run-dirs, surface only new sites
```
python3 scripts/ingest.py [globs...] [--sites-cache F] [--gdb] [--keep N] [--json F]
```
Tiered resolution (cheap → expensive):
1. **stdout, no execution** — aborts carry `file:line: func(): Assertion ...`; fatals
   carry `Fatal Python error: <msg>`. Both dedupe build-stably and for free.
2. **segv** has no reliable C site in stdout → resolve via `--sites-cache <tsv>`
   (precomputed by `segv_sweep.sh`, or written by an in-loop hook) or `--gdb` (runs
   `segv_worker.sh` on demand). Without either, segvs are grouped coarsely and flagged
   `needs-gdb`.

Output: **NEW crash sites** (the work-list for new reports), known-bug vehicle tallies
(with optional `--keep N` prune hint), ambiguous-but-known, and counts of
import-error/clean false alarms.

> The `--sites-cache` must come from the **current** `segv_worker.sh`; a stale cache
> built before a worker fix can mis-resolve segvs to caller frames and surface false
> "new" sites. Regenerate with `segv_sweep.sh` after changing the worker.

## End-to-end (high-volume)

```
# (once / on catalog change) refresh the snapshot
python3 scripts/gen_known_sites.py

# (per batch of run-dirs from the fleet) build a fresh segv cache, then dedupe
bash   scripts/segv_sweep.sh /tmp/sites.tsv 6           # local sites, deterministic
python3 scripts/ingest.py ~/crashers/run-*/* --sites-cache /tmp/sites.tsv --json /tmp/new.json

# triage drafts reports ONLY for the surfaced new sites (docs/SUBAGENT_BRIEF.md),
# then regenerate the snapshot so the next batch dedupes against them too.
```

This collapses a batch of hundreds-to-thousands of dirs to the handful of new sites that
actually need a human/agent — the rest are tallied as vehicles of existing bugs.
