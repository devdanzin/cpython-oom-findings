# Next steps

State: 23 unique bugs (OOM-0001..0023) committed. 882 crash dirs → 38 clusters via
`scripts/cluster_stdout.py`; abort/fatal clusters drafted. SEGV phase + publishing remain.

## 1. Segv phase (~255 dirs)
`cluster_stdout.py` clusters segv only coarsely (by C symbol; the stdout C-stack is
mostly raw offsets). Refine with gdb:
- `C:PyContextVar_Set` (57) → **OOM-0002** vehicles (merge in; don't re-draft)
- `C:PyErr_WarnEx` (26) + much of `C:__libc_start_main` (40) → **OOM-0001** vehicles
- `C:_Py_Dealloc` (90), `C:PyObject_CallOneArg` (33), `C:PyErr_ResourceWarning` (6),
  + singletons → need gdb backtraces to split/dedup; expect ~5–10 NEW segv bugs.
Approach: a drafting Workflow like `oom-draft-clusters`, but each agent first gdb's a
representative to get the real crash site, then dedups vs OOM-0001/0002 before minting
an id (OOM-0024+).

## 2. Deferred abort singletons
`specialize.c:378`, `_interpchannelsmodule.c:443`, `generated_cases.c.h:10539` (1 each).

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
