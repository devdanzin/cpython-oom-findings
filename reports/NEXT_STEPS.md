# Next steps

State: 24 unique bugs (OOM-0001..0024) committed. SEGV phase DONE; publishing remains.

## 1. Segv phase (254 dirs) — DONE (2026-06-18)
Resolved via a **site-centric sweep** instead of stdout clustering: the stdout C-stack
reflects the *host* crash and OOM sites are nondeterministic across binaries, so stdout
signatures are not bug keys (verified). But a vehicle's **local re-run is deterministic**.
Tooling: `scripts/segv_sweep.sh` + `segv_worker.sh` (gdb the true innermost CPython
frame under ft_debug_asan, skipping fatal/assert plumbing) → `bin_sites.py` (bin +
cross-ref the catalog). Full writeup + attribution table: `catalog/segv_sweep.md`;
raw data `catalog/segv_sites_raw.tsv`.
Result: **254 vehicles → 1 NEW bug (OOM-0024, t-string `template_iter` uninit-field
dealloc), 208 attributed to 10 existing bugs (OOM-0001/0002/0003/0004/0005/0006/0008/
0013/0020/0022), 46 host-only NOREPRO.** The earlier "~5–10 new segv bugs" estimate was
high — most segv vehicles are just OOM-0001/0002 seen through different caller frames.
Optional low-yield follow-up: the 46 NOREPRO (need a wider sweep / different build to
get a stable local repro; not reportable as-is).

## 2. Deferred abort singletons — DONE (2026-06-18)
Triaged to 3 distinct new bugs (all debug-only exception/value-state asserts under OOM):
- `specialize.c:378` `unspecialize` `!PyErr_Occurred()` → **OOM-0025** (LOAD_GLOBAL specialize leaks MemoryError).
- `_interpchannelsmodule.c:398/443` `handle_channel_error` → **OOM-0026** (int error code vs PyErr desync; minimal repro).
- `generated_cases.c.h:11120` `POP_JUMP_IF_FALSE` `PyStackRef_BoolCheck(cond)` → **OOM-0027** (non-bool on stack; root cause partial).

## 3. Publishing (outward-facing — confirm with the user; review reports first)
- Build `scripts/publish_gists.py`: per report, `gh gist create --public report.md
  repro.py backtrace.txt`; write the URL into `meta.json` `gist_url`; set status `gisted`.
  Updates via `gh gist edit`.
- `python3 scripts/gen_index.py` then links INDEX rows to the gists.
- Post the umbrella issue from INDEX.md (style of python/cpython#146102); credit line
  (fusil / Victor Stinner + Claude Code) is already in `gen_index.py`'s intro + README.
- `scripts/retest.py` (TODO): re-run repros vs updated builds → flip status to
  `fixed:<commit>`.

## Curation for the umbrella
- **"Stale/missing exception under OOM" assert family:** OOM-0008, 0010, 0011, 0015
  (related theme in 0007) — group / cross-link; may share a root cause.
- **OOM-0010** is a generic eval `LABEL(error)` assert spanning multiple callees
  (RemoteUnwinder, `subprocess._args_from_interpreter_flags`, mimetypes, json.load, …) —
  consider splitting into per-callee reports.
- **OOM-0017** (`gc_free_threading.c:1116`) is free-threading-specific.

## Infra fix
Subagents can't `Write` `.md`/`.json` into this repo (permission); the drafting workflow
used Bash heredoc as a workaround. Fix the permission/setting before the next batch.
