# CLAUDE.md

Guidance for Claude Code (and the maintainer working from another machine) in the
`cpython-oom-findings` repo. This is the **operational hub**: the big picture, the
workflow, the hard-won lessons, and pointers to the focused docs. Read it before doing
triage, minimization, dedup-key, or publishing work here.

## What this repo is

Triage + reporting for crashes found by **fusil** OOM-injection fuzzing
(`_testcapi.set_nomemory`) of CPython `main` (3.16.0a0). One directory per **unique**
CPython bug under `reports/OOM-####-<slug>/`. Crash dirs from the fuzzer are *vehicles*;
many dedupe to the same defect (e.g. ~8 stdlib modules → one `_warnings.c` bug). The end
goal is to publish each finding as a gist and track them from a single **umbrella issue**
(modelled on python/cpython#146102), so CPython devs can pick work without the issue
tracker filling with reports that may not be actionable.

**This is a local-only git repo (branch `master`, no remote).** Concrete local paths
below are this machine's layout — recreate/adjust them on another box (see *Local
environment*).

## Current state (keep this updated)

- **35 unique bugs cataloged (OOM-0001..0035), all committed.** `catalog/SUMMARY.md` is
  the human-facing snapshot table (ID / title / kind / which builds / has-MRE / site).
- **All 35 have a minimal reproducer; 0 are vehicle-confirmed-only.** (The last four —
  OOM-0005/0017/0018/0029 — were minimized in the 2026-06-19 round; see
  `docs/MINIMIZATION.md`.)
- 11 reproduce on a **release** build (the highest-value subset); the rest are
  debug-only asserts (compiled out under `NDEBUG`, where they are latent UB / UAF risk).
- SEGV phase + deferred-singleton phase done; two fleet triages done (everything dedupes
  to the catalog). **Outward-facing publishing has NOT started** (gated on maintainer OK).
- Host-only candidates (don't reproduce locally) are in `catalog/host_only_candidates.md`
  (HOC-1 = the `concurrent_interpreters` `ceval.c:1216` crash, likely fixed upstream by
  GH-150516). Withdrawn non-bugs (harness artifacts) are in `catalog/non_bugs.md`.

## Repo layout

```
reports/OOM-####-<slug>/    one per UNIQUE bug — the SOURCE OF TRUTH
    report.md               the gist body / issue draft (Title, Crash report, Reproducer,
                            Backtrace, Root cause, Suggested fix, Notes, Versions)
    repro.py                minimal, stdlib-only reproducer (deterministic; re-verified)
    backtrace.txt           authoritative gdb/ASan backtrace
    meta.json               id, slug, title, crash_kind, sites[], signature{}, vehicles[],
                            matrix{}, repro_start, status, found_date, confirmed_commit, notes
    vehicle_source.py       the full fuzzer vehicle the repro was reduced from (preserve it!)
catalog/
    SUMMARY.md              the 35-bug snapshot table (regenerate prose by hand)
    known_sites.tsv         flat read-only dedupe snapshot (GENERATED — never hand-edit)
    host_only_candidates.md crashes that don't reproduce locally (HOC-#)
    non_bugs.md             withdrawn candidates (harness artifacts, etc.)
    prior_art.md            issue-tracker check (which findings are already filed)
    norepro_investigation.md / segv_sweep.md  phase writeups + raw data tsvs
docs/
    DEDUP_PIPELINE.md       the single-writer snapshot + ingest design (read this for dedup)
    MINIMIZATION.md         the shrinkray workflow + every minimization lesson
    SUBAGENT_BRIEF.md       per-crash triage procedure for a subagent
scripts/                    gen_known_sites.py, ingest.py, min_oracle.sh, minimize.sh,
                            segv_sweep.sh/segv_worker.sh, gen_index.py, triage_matrix.sh, ...
INDEX.md                    generated umbrella table (do not hand-edit)
```

**One row = one bug.** Vehicles are listed in each report's `meta.json` `vehicles[]`.

## The dedupe model — single-writer, read-only snapshot

`reports/*/meta.json` is the only writer. `scripts/gen_known_sites.py` derives the flat
`catalog/known_sites.tsv` from it (+ each report's `backtrace.txt`). Everything else only
*reads* the snapshot — so there is no shared mutable catalog and no concurrent-write
hazard. The **fuzzer reads it in-loop** to prune ~96%-duplicate crashes live; `ingest.py`
(triage) reconciles a pile of run-dirs against it and surfaces only genuinely-new sites.
Full design + tools: **`docs/DEDUP_PIPELINE.md`**. After ANY catalog change, run
`python3 scripts/gen_known_sites.py` — it also validates every `meta.json` (the fastest
catch for a malformed-JSON note).

### Dedup-key curation — the rule that keeps biting us

`known_sites.tsv` keys a bug by `func` (`file:func`), `line` (`file:line`, near-matched
±12), `assert` (`file:expr`), and `msg` (fatal prefix). The deduper matches a crash
against ALL keys and, on a tie, `decide()` picks `sorted(matched)[0]` (lowest id). So a
**generic detector/plumbing key shared by several bugs causes a mislabel** to the
lowest-numbered one. We have fixed this class of bug **three times**:

- `!PyErr_Occurred()` / `!_PyErr_Occurred(tstate)` asserts (OOM-0011 vs 0025) →
  `GENERIC_ASSERTS` denylist in `gen_known_sites.py`.
- the negative-refcount **detector** (`_Py_NegativeRefcount`, `_PyObject_AssertFailed`,
  `Include/refcount.h:*`, `object.c:275`, the `object has negative ref count` assert) —
  shared by OOM-0005/0019/0029 → `GENERIC_DETECTOR_FUNCS` + `DETECTOR_FILE` +
  `_generic_assert()` (mirrors `oom_dedup._BT_SKIP`/`_BT_SKIP_FILE`).

**Rule:** detector/plumbing frames (the assert machinery, `Py_DECREF`/atomics in
`refcount.h`/`pyatomic*.h`/`object.h`, the generic dealloc dispatch) *catch* corruption —
they are never the defect and must not be discriminating keys. **After `gen_known_sites`,
grep the new bug's keys and prune any generic/shared frame before committing.** The real
discriminator is the bug's own site (the cascade frame, the parser frame, the specific
assert), reached via the resolved backtrace chain.

## Triage / mint a new bug (lifecycle)

1. **Reproduce + backtrace** across the build matrix (`scripts/triage_matrix.sh`, or by
   hand). Record which builds crash. For aborts/asserts the site is in stdout; for segvs
   (and negrefcount/generic-assert aborts) resolve the C site — see *Getting a backtrace*.
2. **Dedupe** against `known_sites.tsv` (run `ingest.py` over the dir, or check by hand).
   MATCH → add the dir to that report's `meta.json` `vehicles[]` and stop. NEW → continue.
3. **Minimize** to a deterministic stdlib-only repro — **`docs/MINIMIZATION.md`**.
4. **Root-cause** by reading CPython source at the faulting frame; write the defect + a
   suggested fix.
5. **Emit** `reports/OOM-####-<slug>/` (report.md/repro.py/backtrace.txt/meta.json,
   `docs/SUBAGENT_BRIEF.md` has the template), **preserve `vehicle_source.py`**, then
   `python3 scripts/gen_known_sites.py` and **prune any generic keys** (above).
6. Update `catalog/SUMMARY.md` (row + the totals line) and commit (see *Commits*).

## Getting a backtrace without (or with) gdb

The faulting C frame is what dedupes a crash; the module is just the vehicle.

- **Aborts/asserts** print `file:line: func(): Assertion ...` in stdout for free.
- **Segvs** on the ASan build print a symbolized native backtrace automatically
  (`#N 0x.. in func /abs/.../file.c:line`); `oom_dedup.extract_native_sites` /
  `ingest.py` parse it straight from stdout — deterministic, no gdb.
- **Aborts on the ASan build** print *no* native backtrace by default. Add
  **`ASAN_OPTIONS=...:handle_abort=1`** → ASan prints a symbolized C backtrace on the
  abort too (keep `abort_on_error=1` to still exit via SIGABRT). This is how negrefcount
  cascades resolve without gdb. **fusil sets this on its children now** (PR #89).
- **faulthandler's** "Current thread's C stack" prints raw offsets for *static* functions
  (`subtype_clear`, `tuple_dealloc`, …) — resolve them with `addr2line -fe <python> 0x…`.
- **gdb** (`scripts/segv_worker.sh`, or `gdb -batch -ex run -ex 'bt 30'`) is the
  fallback. **gdb PERTURBS OOM/thread timing** — it can change which allocation fails and
  even which crash *face* you see (it serialized OOM-0018's cross-thread race into a
  shutdown-GC abort). Prefer the live ASan/faulthandler backtrace; cross-check under gdb.
  gdb is installed and approved for this work.

## Build matrix & reading it

Test every crasher across the local CPython 3.16.0a0 builds (suggest adding configs when
useful):

| build | path (this machine) | notes |
|---|---|---|
| `ft_debug_asan` | `~/projects/3.16_ft_debug_asan_cpython/python` | free-threaded, debug, ASan + asserts — **the triage build** (gdb, refcount/assert checks, `_testcapi.set_nomemory`, source tree) |
| `ft_release` | `~/projects/3.16_ft_release_cpython/python` | free-threaded, release |
| `jit` | `~/projects/jit_cpython/python` | GIL build, JIT (also ASan here) |
| `upstream` | `~/projects/upstream_cpython/python` | GIL build, plain release |

- A crash that aborts on `ft_debug_asan`/`jit` but is `n/a` on the release builds is a
  **debug-only assert** (compiled out under `NDEBUG`) — on release the same defect is a
  latent UB / use-after-free, so it's still a real bug.
- **Exit codes:** an ASan build catches a SIGSEGV and exits **rc 1** ("AddressSanitizer:
  SEGV … ABORTING"); a non-ASan build segvs at **rc 139**. Compare by faulting frame, not
  exit code. Run **without a pipe** (`py x.py >out 2>&1; echo $?`) — a pipe hides the rc.
  (With fusil's new `handle_abort=1:abort_on_error=1`, ASan crashes exit via SIGABRT
  instead — see PR #89 / the fusil notes.)
- **Flag-default gotcha:** some stdlib paths gate on interpreter flags whose *defaults
  differ by build* (e.g. `_py_warnings._use_context = sys.flags.context_aware_warnings`,
  default 1 on FT, 0 on GIL; force with `-X context_aware_warnings=1`). A crash reachable
  only via such a path looks "FT-only" but the C bug is usually build-agnostic —
  `PYTHON_GIL=1` does NOT change init-time flag defaults; reach the path directly.
- **Commit-gated, not clang-gated:** when an OOM crasher won't reproduce on a newer build,
  **diff the commit range first** — a `main` commit may have shifted/fixed it (HOC-1 is
  gated by GH-150516 / `ad1513a263b`, not by the clang version). This is real and will
  bite anyone verifying fixes.

## The fusil side (the producer + the in-loop dedup contract)

The Python OOM fuzzer is in the sibling **`~/projects/fusil`** repo (its own `CLAUDE.md`
has the detail). The contract with this catalog:

- `--oom-fuzz` emits the `set_nomemory` harness; `--oom-dedup-catalog <known_sites.tsv>`
  loads this catalog's snapshot and labels/prunes crash dirs in-loop
  (`-OOM-####` / `-oomNEW` / `-oomSEGV`); `--oom-dedup-prune` drops dups past `--keep N`.
  `--oom-dedup-resolve-segv` re-runs `source.py` under gdb to resolve segvs — now mostly
  unnecessary because the live ASan backtrace is parsed first.
- **handle_abort (fusil PR #89):** fusil now sets `handle_abort=1:abort_on_error=1` in the
  child's `ASAN_OPTIONS`, so aborts print a symbolized backtrace to stdout and the in-loop
  dedup resolves abort sites without a gdb re-run. **The running fleet must be restarted on
  fusil main ≥ the PR-#89 merge to pick this up.**
- **Fleet:** systemd multi-instance runner in fusil `fleet/` (`fleet up/down/status/...`).
  Config on this machine: `/home/danzin/fleet.oca.conf` (env `FLEET_CONF`,
  `F=~/projects/fusil/fleet/fleet`, run as root: `sudo $F down/up <N>`). Runner venvs:
  `~/venvs/fusil_venv` (GIL) and `~/venvs/fusil_ft_venv` (free-threaded). The fleet reads
  `known_sites.tsv` read-only — pushing a snapshot update needs no fleet restart; a fusil
  *code* change does.

## Commits

This repo has **no remote** → branch + `git merge --no-ff` to `master` (keep the branch).
Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

The sibling **fusil** repo uses the full GitHub flow (the maintainer's standing default):
branch → commit → `gh issue create` (problem/desired outcome) → push → `gh pr create`
(implementation, `Closes #N`) → `gh pr merge --merge` (no `--delete-branch`) →
`git push origin --delete <branch>` (keep local). Direct-to-`main` only if the maintainer
says a change is too small. The fusil `CLAUDE.md` is intentionally kept untracked there.

## Local environment (this machine — recreate elsewhere)

- CPython build matrix: the four `~/projects/*_cpython/python` builds above; the
  `ft_debug_asan` one (commit `15d7406`, the `confirmed_commit` for most reports) is the
  triage build. Crashers live under `~/crashers/` (and `~/crashers/host_crashers/` for
  host downloads); the readable fleet output is under `/home/fusil/runs/fleet/`.
- venvs: `~/venvs/shrinkray_venv` (shrinkray), `~/venvs/fusil_venv` / `~/venvs/fusil_ft_venv`
  (fleet runners). `oom_dedup` is pure-Python and imports without the runtime stack.
- Tools: `gdb`, `addr2line`, `ruff` (`/snap/bin/ruff`), `shrinkray`, `creduce`
  (`/usr/bin`). `pyflakes`/`pytest` are NOT installed (fusil tests use `unittest`).
- On another machine: rebuild the four interpreters (or at least `ft_debug_asan`), point
  `OOM_PY` (see `scripts/min_oracle.sh`) at the debug+ASan one, recreate the venvs, and
  sync this repo. The reports/snapshot are portable; the paths are not.

## Pointers

- Dedupe design + tools → `docs/DEDUP_PIPELINE.md`
- Minimization workflow + every lesson → `docs/MINIMIZATION.md`
- Per-crash triage procedure → `docs/SUBAGENT_BRIEF.md`
- What's next (publishing, curation) → `reports/NEXT_STEPS.md`
- Bug snapshot table → `catalog/SUMMARY.md`; upstream-already-filed check → `catalog/prior_art.md`
