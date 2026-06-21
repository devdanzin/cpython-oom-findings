# HANDOFF.md — read this first (new machine / new chat)

Orientation for a fresh Claude Code chat picking up this work on another machine. It
captures *what we do, how, and how we work together* — the parts that live in chat context
and memory rather than in code. The per-repo `CLAUDE.md` files are the canonical operational
detail; this is the map and the working relationship.

## What this is

A long-running effort to find and report **memory-safety bugs in CPython** using **fusil**,
a fuzzer driven into allocation-failure (OOM) error paths via `_testcapi.set_nomemory`. Two
repos work together:

- **`~/projects/fusil`** — the fuzzer (the *producer*). Public: `github.com/devdanzin/fusil`.
  Only the Python OOM/JIT path is actively developed (`fuzzers/fusil-python-threaded`,
  `fusil.python*`). See its `CLAUDE.md`.
- **`~/projects/cpython-oom-findings`** — the *triage + reporting catalog* (one dir per
  unique bug, dedup tooling, the disclosure pipeline). Public:
  `github.com/devdanzin/cpython-oom-findings`. **Start from its `CLAUDE.md`.**

The fuzzer finds crashes (often ~96% duplicates); the catalog dedupes them to unique
defects, minimizes each to a clean stdlib repro, root-causes it against CPython source, and
discloses it (gist + an umbrella issue, or a standalone issue for the strong ones).

## Where things stand (milestones)

- **36 unique bugs cataloged** (`OOM-0001..0036`), each with a minimal deterministic repro.
- **35 published as public gists + an umbrella issue, python/cpython#151763.**
- **OOM-0036** is the headline: found by the new `--oom-seq` fuzzing mode, root-caused to a
  real **`list.append()` double-free under `MemoryError`** in the `_CALL_LIST_APPEND`
  bytecode (steals `arg`, then `ERROR_NO_POP()` leaves it for `exception_unwind` to
  double-close), reproducible **without any test API** (a real `RLIMIT_AS` segfault). Filed
  as **python/cpython#151818**; closely related to (but distinct from) #151119 / PR #151538.
  Full story: `reports/OOM-0036-list-append-oom-double-free/`.
- **fusil `--oom-seq` (Phase 4)** landed: stateful call *sequences* so an allocation failure
  in one call can corrupt state a later call trips over. Design: `fusil/doc/oom-sequences.md`.
  The fleet runs it; OOM-0036 was its first find.
- The fleet (multi-instance systemd fuzzing) runs continuously; in-loop dedup labels crash
  dirs against the catalog snapshot.

## How we work together (please match this)

- **Collaborative and inquisitive.** The maintainer asks a lot of "could we also…/why…/is it
  feasible…" questions — engage them substantively; the back-and-forth is how the good
  findings happen. Offer a recommendation, not just options.
- **Verify before claiming.** Reproduce N times, check across the build matrix, read the
  actual source/diff. Don't assert a root cause you haven't pinned; say "partial" when it is.
  Several big results came from *not* trusting a first-pass conclusion.
- **Outward-facing actions are gated.** Publishing gists, filing/commenting on CPython
  issues, pushing public repos, anything under the maintainer's GitHub identity — propose and
  get an explicit go-ahead; the maintainer reviews and usually posts these themselves.
- **AI disclosure** goes on anything public (gists/issues carry a one-line "drafted with
  Claude Code" note). Be transparent.
- **Dup-check before filing**, by the **culprit C symbol** (e.g. `_PyList_AppendTakeRef`),
  not just the symptom — that's how related issues surface. (We learned this the hard way on
  #151818 vs #151119.)
- **Free-threaded sub-interpreter fuzzing crashes are on filing-hold.** colesbury (FT lead)
  de-prioritized the whole category on **#143232**: "I don't think it's worth fuzzing
  [subinterpreters] for now until the known issues are addressed" (cf. the FT subinterpreter
  data-race umbrella **#129824**). So **don't open upstream issues** for FT-only
  subinterpreter create/destroy/run crashes (e.g. OOM-0020, OOM-0038) for now — keep
  cataloging them (they're real), mark `"filing_hold": "<reason>"` in their `meta.json`, and
  revisit once that area stabilizes. This does **not** cover subinterpreter crashes that also
  hit GIL builds and aren't races (e.g. OOM-0037 stays fileable).
- **Keep the records updated** as you go (the `meta.json`, `SUMMARY.md`, `INDEX.md`, and the
  per-repo `CLAUDE.md`).

## Commit conventions

- **catalog**: branch → `git merge --no-ff` to `main` → push. Trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **fusil**: full GitHub flow — branch → `gh issue create` (problem) → push → `gh pr create`
  (`Closes #N`) → `gh pr merge --merge` → `git push origin --delete <branch>` (keep local).
  Direct-to-`main` only for changes the maintainer calls too small.
- Commit/push only when asked. End PR bodies with the Claude Code generation note.

## Techniques worth knowing (hard-won)

- **UAF producer-pinning:** on a `--with-pymalloc` **+ ASan** build, run with
  `PYTHONMALLOC=malloc` → frees go through ASan → a `heap-use-after-free` report with the
  **freed-by** (the bug) and **allocated-by** (the victim) stacks. This is what cracked
  OOM-0036. (A `--without-pymalloc` ASan build rejects `PYTHONMALLOC=malloc`.)
- **Abort backtraces without gdb:** `ASAN_OPTIONS=...:handle_abort=1:abort_on_error=1` makes
  ASan print a symbolized C backtrace on an abort (e.g. negative-refcount). fusil sets this
  on its children (PR #89).
- **Specialized-opcode bugs:** if a crash needs a *warm-up* to reproduce, suspect a
  *specialized* bytecode. `dis.dis(f, adaptive=True)` after warming + reading the uop in
  `Python/bytecodes.c` often pins it (it did for OOM-0036) — no rr needed.
- **Minimization:** shrinkray with a signature-pinned, repeat-run oracle; cold-call bugs
  need a *subprocess self-sweep* (fresh process per `set_nomemory` start) — see
  `docs/MINIMIZATION.md`.
- **gdb perturbs OOM/thread timing** — prefer live ASan/faulthandler backtraces; cross-check
  under gdb. **rr + ASan doesn't record** (MADV_GUARD_INSTALL vs older rr) — use a non-ASan
  build for rr.

## Pointers

- Catalog operations, dedup model, build matrix, lifecycle → `cpython-oom-findings/CLAUDE.md`
- Recreate the build/venv/tool environment → `docs/ENVIRONMENT.md`
- Root machine setup (fusil user, fleet, perms) → `scripts/setup_machine.sh`
- Minimization workflow + lessons → `docs/MINIMIZATION.md`; dedup design → `docs/DEDUP_PIPELINE.md`
- fusil internals (OOM modes, `--oom-seq`, fleet, plugins) → `fusil/CLAUDE.md`, `fusil/doc/`
- What's next → `reports/NEXT_STEPS.md`
