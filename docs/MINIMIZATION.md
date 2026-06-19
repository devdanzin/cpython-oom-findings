# Minimization: turning a fat fuzzer vehicle into a minimal reproducer

A fuzzer *vehicle* (`vehicle_source.py`, ~500 lines) reaches a CPython bug through a lot
of incidental machinery. The goal is a small, **deterministic, stdlib-only** `repro.py`
that triggers the *same* defect. This is `shrinkray` driven by a **signature-pinned
oracle**, followed by hand-cleanup. Every lesson below was paid for in a real reduction.

## The pieces

- **`scripts/min_oracle.sh`** — the interestingness oracle. Exit 0 iff the candidate still
  crashes with the bug's `OOM_SIG` regex within `OOM_N` runs. **Pinning the signature is
  essential**: vehicles are multi-bug, so an "any crash" oracle reduces toward a *different*
  bug. Env knobs: `OOM_PY` (interpreter, default the ft_debug_asan build), `OOM_GIL`
  (`PYTHON_GIL`), `OOM_SIG` (REQUIRED regex), `OOM_N` (runs/candidate), `OOM_T` (per-run
  timeout), **`OOM_ASAN`** (ASAN_OPTIONS — set
  `detect_leaks=0:abort_on_error=0:handle_abort=1` to pin a *dealloc-cascade frame* of an
  abort, since handle_abort prints a symbolized backtrace — see below).
- **`scripts/minimize.sh`** — drives `shrinkray --input-type arg` with the oracle. creduce
  (`/usr/bin`) is the fallback.
- **`shrinkray`** at `~/venvs/shrinkray_venv/bin/shrinkray`.

## Workflow

1. **Find a vehicle.** If `reports/OOM-####/vehicle_source.py` exists, use it. Otherwise
   fish one from the fleet/`~/crashers` by crash signature (re-run candidates, keep one
   that reproduces the target site deterministically). **Always preserve the vehicle** in
   the report dir.
2. **Pick a distinctive `OOM_SIG`.** The bug's discriminating assert/site, e.g.
   `_PyUnicode_NONCOMPACT_DATA`, `gc_get_refs\(op\) >= 0`, `pycore_stackref\.h:726`,
   `tuple_dealloc.*tupleobject\.c:277`. Confirm the right `OOM_GIL` (some bugs are
   free-threading-only → `OOM_GIL=0`). Sanity-check the oracle on the FULL vehicle first.
3. **Speed levers** (the first pilot stalled 45 min without them): lower the vehicle's
   `_OOM_MAX_START` (sed to ~150) so non-crashing candidates don't run the full 1000-iter
   sweep to the timeout; `OOM_N=2-3` for deterministic bugs; shrinkray `--timeout 30`;
   **reduce the file IN PLACE on a stable path** (`/tmp/min_oomNN/cand.py`) so a
   timeout-kill keeps the partial (shrinkray writes incrementally).
4. **Run** at `--parallelism ≤6` (cap total shrinkray workers at 6 on the 8-core laptop —
   pause the fleet first, or run one bug at a time). Reduce in the background.
5. **Re-verify + clean** (below), then **promote**: write `repro.py`, update report
   Reproducer + Notes + `meta.json` (Minimization PARTIAL → DONE), flip `SUMMARY.md` MRE
   `no → yes` and the totals, commit.

## The cleanup convention (maintainer's, applies at EVERY promotion)

shrinkray output is a STARTING POINT, never committed verbatim. Before promoting:
1. Reformat to clean PEP8-ish Python.
2. Rename mangled names (`a`/`l`/`oks`/`_start` → `run`/`func`/`start`/…).
3. Inline single-use constants (`_OOM_MAX_START=32` → `range(32)`).
4. Flatten the `oom_call` wrapper to a bare loop **when it still fires**.
5. **Re-verify the cleaned version reproduces (oracle, N ≥ 20, ideally 50) BEFORE
   committing**, and measure the per-run hit rate so the report is honest.

But — see the next lesson before you delete anything.

## Lessons (the expensive ones)

- **shrinkray keeps only load-bearing elements.** What it *kept* is usually essential —
  so when a clean rewrite fails, don't guess: **bisect**. Reformat-verbatim first (proves
  formatting is safe), then test each simplification individually against the working
  baseline, and combine only the green ones. Examples of non-obvious load-bearing pieces:
  - OOM-0011 needs `import asyncio` (shifts the allocation window).
  - OOM-0025 needs `func(*args)` (a *specialized CALL*, not `func()`) **and** a bare
    *undefined* global in a `finally` (a `LOAD_GLOBAL` that is the instruction specialized
    at the crash; a *defined* name short-circuits and doesn't reproduce). It is a
    specializer bug, so the exact bytecode form matters.
  - OOM-0029 needs the exact arg `"\x004\x8A\xD5\x03"` (NUL/control + high bytes); every
    simpler string, even dropping the leading NUL, is 0/20.
  - Conversely, OOM-0017's `finally:` and OOM-0029's `finally:` were *not* load-bearing —
    shrinkray just never removed them. Always bisect rather than assume either way.
- **The "allocation-baseline sensitivity" worry is often a RED HERRING.** A reduction may
  *look* like it needs the surrounding setup to fix the allocation count, but test the
  stripped version before believing it. OOM-0017's report claimed it was
  "alignment-sensitive, needs the fuzzer boilerplate" — false; `socket.recv_fds(0,0,0)`
  under the sweep reproduces on its own.
- **Substitute-then-strip** (when shrinkray gets STUCK keeping a big setup block):
  shrinkray can't delete code the *final call's argument* still references (e.g. the
  fuzzer's `weird_classes`/`WeirdBase` machinery). Fix by hand: substitute a **trivial
  object** (`0`, `None`, a literal) for that argument, re-verify, and the setup becomes
  dead → removable. This collapsed OOM-0005 from a stuck 25-line reduction (full
  `weird_classes` setup) to a clean `xml.dom.minidom.parse(0)` sweep.
- **Widen the sweep when it helps, but watch for a window.** For finalize/GC-timed bugs
  only the *final* `set_nomemory(N)` matters, and the working window can be bounded:
  OOM-0018 reproduces for `N` in ~[113, 900] (a `set_nomemory(200); (MagicMock(),
  undefined_name)` 4-liner) but `range(1000)` overshoots shutdown GC and fails. Probe the
  window; pick a central value; document it. (Counter-intuitively a *narrower* range can
  raise the per-run hit rate — OOM-0017 is 15/20 at `range(259)` but 9/20 at `range(1000)`.)
- **Pin abort cascades with `handle_abort`.** A negrefcount/generic-assert abort's only
  stdout signature is the generic detector (`refcount.h:520`), which can't distinguish it
  from sibling bugs. Set `OOM_ASAN=detect_leaks=0:abort_on_error=0:handle_abort=1` so ASan
  prints a **symbolized** backtrace at the abort, and pin `OOM_SIG` to the real cascade
  frame (`tuple_dealloc.*tupleobject\.c:277`). Non-perturbing, no gdb, no addr2line — and
  the cascade was byte-identical 10/10. This is how OOM-0029 was reduced.
- **Verify the vehicle's ACTUAL deterministic crash path before trusting a report's
  mechanism.** OOM-0018's report claimed a cross-thread race (caught once under gdb); a
  210-run census (resolving the caller frame with `addr2line`) showed it is deterministically
  a *shutdown-GC* clear (160/160 no-gdb, 50/50 under gdb, 0 cross-thread). gdb did not
  perturb the face here; the cross-thread route is host-specific (pre-`ad1513a263b`). When
  a reduction "drifts" to a different mechanism, check whether the full vehicle takes that
  path too — the reduction may be faithful and the report wrong.
- **Measurement hygiene:** static C functions (`subtype_clear`, `tuple_dealloc`) are
  unsymbolized in faulthandler's C-stack — resolve the offset with `addr2line`, don't
  keyword-grep the whole stack (a `HandlePending`-anywhere grep once gave a false
  "cross-thread" verdict). gdb `bt` is authoritative but perturbs timing; the faulthandler
  C-stack and the ASan `handle_abort` backtrace are non-perturbing.

## Watch-outs

- Running OOM repros from the repo CWD drops stray arg-named artifact files
  (`weird_set(...)`, float-named) — fusil arg-generator side effects. Run from a scratch
  dir, or rely on `.gitignore` (it covers `0.[0-9]*`, `weird_*`, `.shrinkray/`).
- Embedding a repro snippet in a `meta.json` `notes` string: **escape inner `"`** or
  rephrase — an unescaped quote (`_strptime("","")`) is invalid JSON and breaks
  `gen_known_sites.py` for the whole catalog. Always run `gen_known_sites.py` after editing
  a `meta.json`; it validates every file.
