# Next steps

**State: 39 unique bugs (OOM-0001..0039), all committed, each with a minimal reproducer.**
Discovery, triage, minimization, and the dedup pipeline are mature. OOM-0001..0035 are
published as public gists under the umbrella **python/cpython#151763**; **OOM-0036** is filed
as its own issue **python/cpython#151818**. The live work is finishing the three newest finds
and watching the filed issues for fixes.

## Open work

### 1. OOM-0037 / OOM-0039 — publish + file (outward-facing; gated on the maintainer)

Both are `drafted`, have minimal stdlib repros, and look novel and fileable:

- **OOM-0037** — subinterpreter *unraisable-hook* structseq crash. Hits beyond the FT-only
  race category, so it is fileable (it does **not** fall under the filing-hold note below).
- **OOM-0039** — `deque.clear()`'s `PyErr_Clear` clobbers an in-flight exception under OOM.

Before filing: **dup-check by the culprit C symbol** (not the symptom — that's how the
#151818-vs-#151119 relationship surfaced), publish the gist (`scripts/publish_gists.py`), set
`status: gisted` + `gist_url`, then file (standalone, or fold under the umbrella #151763).

### 2. OOM-0038 — keep on filing-hold

Free-threaded subinterpreter creation crash (indexpool / TLBC reserve with no tstate). Real
and novel, but in the category colesbury (FT lead) de-prioritized on **#143232** (cf. the FT
subinterpreter data-race umbrella **#129824**). Stays catalog-only — its `meta.json` carries
the `filing_hold`. Revisit once that area stabilizes.

### 3. Watch the filed issues → mark fixed

When **#151818** (OOM-0036), entries under **#151763**, or **#151673** (OOM-0001) get fixes,
re-run the repro on an updated build and flip the relevant `meta.json` to
`status: fixed:<commit>`. Mind the **commit-gated** reproducibility lesson (build matrix in
`CLAUDE.md`): diff the commit range before declaring a NOREPRO. (A `scripts/retest.py` to
automate the re-run is still a TODO.)

## Standing / lower-priority

- **Curation for the umbrella** — the "stale/missing exception under OOM" assert family
  (OOM-0008, 0010, 0011, 0015; related theme in 0007, 0032) can be grouped / cross-linked.
  **OOM-0010** is a generic eval `LABEL(error)` assert spanning multiple callees and could be
  split into per-callee reports.
- **Root cause still PARTIAL** (trigger minimal, exact defect line not pinned): OOM-0010
  (split), OOM-0027, OOM-0029 (needs a refcount watchpoint on the over-decref'd MemoryError),
  OOM-0033, OOM-0035.
- **Host-only candidates** (`catalog/host_only_candidates.md`): **HOC-1**
  (`concurrent_interpreters` `ceval.c:1216`) reproduces on the host but not locally — likely
  fixed upstream by GH-150516. Build the host commit with clang-22 to confirm if ever worth
  filing. Low priority.

## Operational

- **Fleet** runs on fusil `main` (now ships `--oom-seq` + `--oom-seq-randomize` and the
  hardened in-loop deduper); it keeps deduping new crashes against `known_sites.tsv`. When
  new fleet finds appear, triage → dedup → mint the next OOM-00NN.
- Build/venv/tool recreation → `docs/ENVIRONMENT.md`; root machine setup → `scripts/setup_machine.sh`.

## Done (history)

- **Publishing** — `scripts/publish_gists.py` built; OOM-0001..0035 published as public gists;
  umbrella **#151763** posted; all 35 gists backlink the umbrella.
- **OOM-0036** — root-caused to a `_CALL_LIST_APPEND` double-free, audited across all 440 ops
  in `bytecodes.c` (the lone offender), reproduced **without `_testcapi`** (a real `RLIMIT_AS`
  cap → SEGV), filed as **#151818**, and cross-referenced to the related-but-distinct
  **#151119 / PR #151538**. The UAF producer was pinned on a GIL+ASan build under
  `PYTHONMALLOC=malloc` (free-stack technique; see `CLAUDE.md` build matrix).
- **fusil `--oom-seq` (Phase 4)** + `--oom-seq-randomize` landed (found OOM-0036, unreachable
  by the single-call fail-forever harness). In-loop deduper hardened (faulthandler/family
  matching, bounded stdout reads, never aborts a session on a dedupe failure).
- **SEGV phase** (254 dirs → OOM-0024 + 208 attributions + 46 NOREPRO), **deferred-abort
  singletons** (OOM-0025/0026/0027), **fleet triages** (OOM-0030..0035), **minimization round**
  — every bug now has an MRE. See `catalog/segv_sweep.md`, `docs/MINIMIZATION.md`.
- **Threaded-OOM "corruption" = harness artifact** identified and fixed in fusil (the
  per-iteration allocator swap raced live worker threads); retired the long-parked
  multiprocessing `resource_sharer` "nut" (it was masking the already-cataloged OOM-0018) and
  several batch candidates. See `catalog/non_bugs.md`.
