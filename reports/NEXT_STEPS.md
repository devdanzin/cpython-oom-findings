# Next steps

**State: 35 unique bugs (OOM-0001..0035), all committed, all with a minimal reproducer
(0 vehicle-confirmed-only).** Discovery + triage + minimization phases are done; the
dedupe pipeline is mature. The big remaining work is **outward-facing publishing**, which
is gated on the maintainer.

## Done

- **SEGV phase** (254 dirs) — site-centric sweep → 1 new bug (OOM-0024) + 208 attributed
  + 46 host-only NOREPRO. (`catalog/segv_sweep.md`, `catalog/norepro_investigation.md`.)
- **Deferred abort singletons** → OOM-0025/0026/0027.
- **Local fleet** built (fusil `fleet/`) + **two fleet triages** (759 then 1188 dirs) —
  everything dedupes to the catalog; first fleet-found bugs OOM-0030..0035.
- **Minimization round (2026-06-19)** — the last 4 "hard" vehicle-confirmed bugs reduced:
  OOM-0005 (`xml.dom.minidom.parse(0)`), OOM-0017 (`socket.recv_fds(0,0,0)`), OOM-0018
  (`set_nomemory(200); (MagicMock(), undefined_name)`), OOM-0029
  (`_pyrepl.utils.disp_str("\x004\x8A\xD5\x03")`). See `docs/MINIMIZATION.md`.
- **Dedup quality** — in-loop deduper hardened (native-backtrace parse + header-skip);
  `handle_abort` symbolized-abort backtraces landed in fusil (PR #89); negrefcount
  detector-key collision fixed (OOM-0029 no longer mislabeled OOM-0019).
- **Infra:** subagents can now `Write` into this out-of-project repo
  (`~/.claude/settings.json` `permissions.additionalDirectories`) — the old Bash-heredoc
  workaround is no longer needed.

## 1. Publishing (outward-facing — confirm with the maintainer; review all reports first)

The catalog is in good shape for this (35/35 with MREs, clean dedup). `prior_art.md`:
only **OOM-0001** is already filed (python/cpython#151673); the other 34 look novel.

- **Build `scripts/publish_gists.py`** (TODO): per report, `gh gist create --public
  report.md repro.py backtrace.txt`; write the URL into `meta.json` `gist_url`; set
  `status: gisted`. Updates via `gh gist edit`.
- `python3 scripts/gen_index.py` → regenerate `INDEX.md`; link rows to the gists.
- **Post the umbrella issue** from `INDEX.md` (style of python/cpython#146102). The credit
  line (fusil / Victor Stinner + Claude Code; `_AI Disclaimer:_` per report) is already in
  `gen_index.py`'s intro + `README.md`.
- **Suggested first batch** — the release-crashing bugs with MREs (highest confidence,
  lowest verify effort), per `SUMMARY.md`: **OOM-0001, 0002, 0005, 0012, 0014, 0020, 0028,
  0031, 0033, 0034**. OOM-0034/0028 are the cleanest one-line unchecked-alloc NULL derefs;
  OOM-0005 is the most severe (eval stackref over-decref → UAF on release).

## 2. retest as builds move (TODO)

`scripts/retest.py`: re-run each `repro.py` against an updated interpreter → flip
`status` to `fixed:<commit>` when it stops crashing. Useful once any of these are filed.
Note the **commit-gated** reproducibility lesson (build matrix in `CLAUDE.md`) — diff the
commit range before declaring a NOREPRO.

## 3. Curation for the umbrella

- **"Stale/missing exception under OOM" assert family:** OOM-0008, 0010, 0011, 0015
  (related theme in 0007, 0032) — group / cross-link; may share a root cause.
- **OOM-0010** is a generic eval `LABEL(error)` assert spanning multiple callees
  (RemoteUnwinder, `subprocess._args_from_interpreter_flags`, mimetypes, json.load, …) —
  consider splitting into per-callee reports.
- Free-threading-specific: **OOM-0017** (FT GC), **OOM-0018** (managed-dict). Note
  OOM-0018's deterministic local face is shutdown-GC, not the cross-thread race the report
  also shows (host-specific) — say so when filing.
- **Root cause still PARTIAL** (trigger minimal, exact defect line not pinned): OOM-0010
  (split), OOM-0027, OOM-0029 (needs a refcount watchpoint on the over-decref'd
  MemoryError), OOM-0035, OOM-0033.

## 4. Host-only candidates

`catalog/host_only_candidates.md`: **HOC-1** (`concurrent_interpreters` `ceval.c:1216`)
reproduces reliably on the host (pre-`ad1513a263b` build) but not locally — likely fixed
upstream by GH-150516. To confirm decisively, build the host commit `65afcdd8dfb` with
clang-22 (isolates commit from compiler) and re-run. Low priority unless we want to file it.

## 5. Operational

- **Restart the fleet on fusil main ≥ the PR-#89 merge** so it gets `handle_abort` (the
  detector-key fix is already live — the fleet reads `known_sites.tsv`).
- Optional fusil follow-up: classify a resolved `_testcapi/mem.c` hook site as
  `oomHARNESS` so the FT `set_nomemory`-race artifact (see `catalog/non_bugs.md`)
  auto-files instead of surfacing as `oomNEW`/`oomSEGV`.
