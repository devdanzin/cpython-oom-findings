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

**Public on GitHub: `github.com/devdanzin/cpython-oom-findings` (branch `main`).** Concrete
local paths below are one machine's layout — recreate/adjust on another box (see *Local
environment* and `docs/ENVIRONMENT.md`). **On a new machine / new chat, read `HANDOFF.md`
first.**

## Current state (keep this updated)

- **36 unique bugs cataloged**, all committed, each with a reproducer. IDs run
  **OOM-0001..0042**; **six ids retired** — OOM-0005, OOM-0029, OOM-0033, OOM-0041 were all
  `rr`-proven to be **OOM-0036** at different detector sites and folded into it; OOM-0011 →
  **OOM-0008** (same `f_back`-swallow); OOM-0042 → **OOM-0040** (same extensions-cache key-alloc
  failure, GET-path face) — see the over-decref / stale-exception rules under *Dedup-key
  curation*. `catalog/SUMMARY.md` is the snapshot table.
- **Published:** OOM-0001..0035 are public gists, tracked from the umbrella issue
  **python/cpython#151763**. **OOM-0036** is filed as its own issue,
  **python/cpython#151818** — a `list.append()` double-free under `MemoryError` in the
  `_CALL_LIST_APPEND` bytecode; found by fusil's `--oom-seq` mode; reproduces *without*
  `_testcapi` via a real `RLIMIT_AS` cap. **It is the catalog's most prolific duplicator** —
  rr keeps revealing other entries to be faces of it. Watch the issues for fixes → set
  `status: fixed:<commit>` on the relevant `meta.json`.
- **Newest finds (`drafted`, not yet gisted):** OOM-0037 (subinterpreter unraisable-hook
  structseq), OOM-0039 (`deque.clear()` `PyErr_Clear` clobbers an in-flight exception), and
  **OOM-0040** (extensions-cache key-alloc failure under OOM: NULL-key `strlen` segv on the SET
  path + stale-`MemoryError` `import_run_extension:2301` abort on the GET path — the latter was
  the `rr`-folded OOM-0042) are filing candidates; **OOM-0038** (FT-subinterpreter indexpool/tlbc
  reserve) is on `filing_hold` per upstream guidance (#143232). See `reports/NEXT_STEPS.md`.
- ~12 reproduce on a **release** build (highest-value); the rest are debug-only asserts
  (compiled out under `NDEBUG`, where the same defect is latent UB / UAF).
- **`rr` works on this box** (after the Zen SpecLockMap workaround) and is now the primary
  tool for pinning over-decref/UAF *producers* — see the over-decref rule under *Dedup-key
  curation* and the recipe in *Getting a backtrace*.
- SEGV + deferred-singleton phases done; fleet triages keep deduping to the catalog. Host-
  only candidates → `catalog/host_only_candidates.md` (HOC-1 likely fixed by GH-150516);
  withdrawn non-bugs (harness artifacts) → `catalog/non_bugs.md`.

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
lowest-numbered one. We have fixed this class of bug **repeatedly**:

- `!PyErr_Occurred()` / `!_PyErr_Occurred(tstate)` asserts (OOM-0011 vs 0025) →
  `GENERIC_ASSERTS` denylist in `gen_known_sites.py`.
- the negative-refcount **detector** (`_Py_NegativeRefcount`, `_PyObject_AssertFailed`,
  `Include/refcount.h:*`, `object.c:275`, the `object has negative ref count` assert) —
  shared by OOM-0005/0019/0029 → `GENERIC_DETECTOR_FUNCS` + `DETECTOR_FILE` +
  `_generic_assert()` (mirrors `oom_dedup._BT_SKIP`/`_BT_SKIP_FILE`).
- the **eval-loop operand-stack teardown** frames (`PyStackRef_XCLOSE`,
  `_PyFrame_ClearLocals`, `_PyFrame_ClearExceptCode`, `clear_thread_frame`) — shared by
  OOM-0007/0023 and the (now-folded) OOM-0005; keying them mislabeled OOM-0036 as a
  separate "OOM-0005". Added to `GENERIC_DETECTOR_FUNCS`. A bare `frame.c:101` over-decref
  abort now correctly surfaces as `oomNEW` → triage.

**Rule:** detector/plumbing frames (the assert machinery, `Py_DECREF`/atomics in
`refcount.h`/`pyatomic*.h`/`object.h`, the generic dealloc dispatch, the eval-loop
stack-teardown) *catch* corruption — they are never the defect and must not be
discriminating keys. **After `gen_known_sites`, grep the new bug's keys and prune any
generic/shared frame before committing.** The real discriminator is the bug's own site
(the cascade frame, the parser frame, the specific assert), reached via the resolved
backtrace chain.

**Rule (over-decref / negref / double-free / UAF): `rr`-check the *producer* before
minting it as a new bug.** These crashes surface at a *detector* (a later
dealloc/teardown/refcount-check tripping over an already-corrupted object); the detector
site is **not** the bug and varies by which path holds the second reference. Reverse-execution
is the only reliable way to find the producer — and in practice it is *very often*
[OOM-0036](reports/OOM-0036-list-append-oom-double-free/report.md), the `_CALL_LIST_APPEND`
`list.append()`-under-`MemoryError` double-free: **four** separately-cataloged entries
(OOM-0005/0029/0033/0041) turned out to be OOM-0036 reached via different stdlib paths that
internally `list.append` a second-referenced object under OOM. **Procedure** (needs the Zen
SpecLockMap workaround; see *Local environment*): record the vehicle under `rr`, break at the
detector, `watch -l` the victim's `ob_ref_local` (`+0xc`) and `reverse-continue` through its
full incref/decref ledger **back to allocation** (do not stop early — a partial trace twice
mislabeled OOM-0036); a `_PyList_AppendTakeRefListResize@listobject.c:531` ← `_CALL_LIST_APPEND`
decref of the victim ⇒ it's OOM-0036, **fold it** (`status: "folded"`, `folded_into`). FT
`PyObject` offsets: `ob_ref_local@+0xc`, `ob_ref_shared@+0x10`, `ob_type@+0x18`; for a SEGV
victim, `handle SIGSEGV nostop noprint pass` before `reverse-continue`.

## Triage / mint a new bug (lifecycle)

1. **Reproduce + backtrace** across the build matrix (`scripts/triage_matrix.sh`, or by
   hand). Record which builds crash. For aborts/asserts the site is in stdout; for segvs
   (and negrefcount/generic-assert aborts) resolve the C site — see *Getting a backtrace*.
2. **Dedupe** against `known_sites.tsv` (run `ingest.py` over the dir, or check by hand).
   MATCH → add the dir to that report's `meta.json` `vehicles[]` and stop. NEW → continue.
   **If it's an over-decref / negref / double-free / UAF, `rr`-check the producer before
   treating it as NEW** (see the over-decref rule above) — it is very often OOM-0036 at a
   new detector site. A confirmed-duplicate existing entry is *folded*, not deleted: set its
   `meta.json` `status: "folded"` + `folded_into: "OOM-####"`, leave a redirect `report.md`,
   keep its artifacts; the generators skip `status == "folded"` (not counted, emits no keys).
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
useful).

> **Paths: use `scripts/env.sh`.** The build matrix now lives at
> `~/projects/python_build_matrix/builds/` with the naming
> `{debug,release}-{ft,gil}-{nojit,jit}[-asan]` (workhorse = `debug-ft-nojit-asan`, the
> `ft_debug_asan` analog). All triage/minimization scripts resolve interpreters through
> `scripts/env.sh` (`OOM_PY`, `MATRIX_ROOT`, `MATRIX_BUILDS`, `find_shrinkray`) and every
> value is env-overridable. The table below maps the **logical names** the docs use to that
> matrix; the old `~/projects/3.16_*_cpython` paths are the legacy layout.

| logical build | legacy path / matrix dir | notes |
|---|---|---|
| `ft_debug_asan` | `~/projects/3.16_ft_debug_asan_cpython/python` | free-threaded, debug, ASan + asserts — **the triage build** (gdb, refcount/assert checks, `_testcapi.set_nomemory`, source tree) |
| `debug_asan_pymalloc` | `~/projects/3.16_debug_asan_pymalloc/python` | GIL, debug, ASan. **Dir name is a misnomer** — ASan forces `WITH_PYMALLOC=0`, so it is *not* a pymalloc build. Being a **GIL** build it accepts `PYTHONMALLOC=malloc`, so frees route through ASan → **UAF reports with the free stack** (how OOM-0036's producer was pinned). The free-threaded `ft_debug_asan` build pins mimalloc (required by the FT GC) and rejects `PYTHONMALLOC=malloc` — so the gating is GIL-vs-free-threaded, not pymalloc. |
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

Branch + `git merge --no-ff` to `main` (keep the branch), then `git push origin main`.
Trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

The sibling **fusil** repo uses the full GitHub flow (the maintainer's standing default):
branch → commit → `gh issue create` (problem/desired outcome) → push → `gh pr create`
(implementation, `Closes #N`) → `gh pr merge --merge` (no `--delete-branch`) →
`git push origin --delete <branch>` (keep local). Direct-to-`main` only if the maintainer
says a change is too small. The fusil `CLAUDE.md` is now **committed** in that repo too.

## Local environment (this machine — recreate elsewhere)

- CPython build matrix: the four `~/projects/*_cpython/python` builds above; the
  `ft_debug_asan` one (commit `15d7406`, the `confirmed_commit` for most reports) is the
  triage build. Crashers live under `~/crashers/` (and `~/crashers/host_crashers/` for
  host downloads); the readable fleet output is under `/home/fusil/runs/fleet/`.
- venvs: `~/venvs/shrinkray_venv` (shrinkray), `~/venvs/fusil_venv` / `~/venvs/fusil_ft_venv`
  (fleet runners). `oom_dedup` is pure-Python and imports without the runtime stack.
- Tools: `gdb`, `addr2line`, `ruff` (`/snap/bin/ruff`), `shrinkray`, `creduce`
  (`/usr/bin`). `pyflakes`/`pytest` are NOT installed (fusil tests use `unittest`).
- On another machine: run `scripts/setup_machine.sh` as root (creates the `fusil` user +
  fleet dirs + permissions), then rebuild the interpreters (at least `ft_debug_asan` and
  `debug_asan_pymalloc`), recreate the venvs, and `git clone` both repos — full steps in
  **`docs/ENVIRONMENT.md`**. The reports/snapshot are portable; the paths are not.

## Pointers

- **New machine / new chat → `HANDOFF.md`** (what we do + how we work together)
- Recreate the build/venv/tool environment → `docs/ENVIRONMENT.md`
- Root machine setup (the `fusil` user, fleet dirs, permissions) → `scripts/setup_machine.sh`
- Dedupe design + tools → `docs/DEDUP_PIPELINE.md`
- Minimization workflow + every lesson → `docs/MINIMIZATION.md`
- Per-crash triage procedure → `docs/SUBAGENT_BRIEF.md`
- What's next (publishing, curation) → `reports/NEXT_STEPS.md`
- Bug snapshot table → `catalog/SUMMARY.md`; upstream-already-filed check → `catalog/prior_art.md`
