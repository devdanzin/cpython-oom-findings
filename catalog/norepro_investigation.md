# NOREPRO investigation — the 46 segv vehicles that didn't reproduce locally

The segv site-sweep (`catalog/segv_sweep.md`) left 46 vehicles as NOREPRO — but that
label only meant *did not crash under gdb on `ft_debug_asan` with the default GIL*.
This follow-up answers three questions about them.

## 1. What do their host stdouts show? (no new bug)

Mining the saved host `stdout` of all 46 (`scripts/cluster_segv.py`-style) — the host
*did* crash each one; the families are:

- **~23 → `PyContextVar_Set` / `_pydecimal getcontext|setcontext`** = host-side **OOM-0002**.
- **~21 → `_Py_Dealloc <- PyList_New` / tuple-from-stackref** (namedtuple, ElementTree,
  email, …) = the list/tuple-build-under-OOM dealloc cascade → **OOM-0001/0004/0005/0013/0019/0020**.
- **1 outlier**: `PyType_IsSubtype <- PyObject_CallMethodObjArgs <- PyImport_ImportModuleLevelObject`
  (`multiprocessing_forkserver`, import-time) — the only host crash not obviously a
  known site; still host-only (below), so no local backtrace to confirm.
  **RESOLVED 2026-06-19 → [OOM-0033](../reports/OOM-0033-import-syspath-oom-over-decref/report.md):**
  reproduced locally from the fleet (`multiprocessing.forkserver._handle_preload` does
  `sys.path[:] = <string>` then `__import__`). Root: an import under OOM over-decrefs a
  `sys.path` entry; the freed entry is read by `_get_spec`'s `isinstance(entry, str)` →
  `PyType_IsSubtype` segv (`typeobject.c:2931`), or re-decreffed by the next list
  slice-assignment → `_Py_NegativeRefcount` (`list_ass_slice_lock_held`, `listobject.c:1030`).
  Deterministic minimal repro: `sys.path[:] = "<unicode>"; __import__("H")` under the sweep.

No clearly-novel bug is visible in the 46 host crash signatures.

## 2. Do they reproduce on the full matrix / trying harder? (partly — all known bugs)

The original sweep tested **one** configuration (`ft_debug_asan`, GIL on, under gdb).
Re-running all 46 across the 4-build matrix × both GIL modes × direct-run (gdb-free),
2 runs each (`scripts/norepro_matrix.sh` → `scripts/repro_collect.sh`):

| configuration | recovered | sites (all map to KNOWN bugs) |
|---|---:|---|
| GIL **on**, all builds | 5/46 | `jit:generated_cases.c.h:13867` + `upstream:tuple_alloc@tupleobject.c:46` → **OOM-0005/0019** (stackref negative refcount) |
| GIL **off** (host-faithful), all builds | 15/46 | `ft_debug_asan:_PyMem_DebugCheckAddress@obmalloc.c:3344` → **OOM-0020**; release faces `list_dealloc@listobject.c:567`, `_mi_page_malloc`/`_mi_heap_area_visit_blocks` (mimalloc) |

≈ **20/46 recovered** (the two GIL modes recover **disjoint** subsets), **all attributable
to existing bugs**; ≈ **26/46 still don't reproduce on any local build/GIL combo**.

**Three reproduction axes we'd been ignoring** (why the original sweep under-counted):
1. **Build** — some reproduce only on `jit` or only on release (mimalloc/list_dealloc).
2. **GIL mode** — `PYTHON_GIL=0` (what fusil used) vs default-on recover *different*
   crashes; the xml_etree set is GIL-on-only, the heap-corruption set is GIL-off-mostly.
3. **gdb perturbs timing** — several crash on a direct run but not under gdb; collect the
   backtrace in a *second* pass, don't gate reproduction on the gdb run.

The ~26 hold-outs are **host-binary-specific**: OOM crash sites shift with the exact
compilation, and the host's `upstream_cpython` (a free-threaded debug+ASan build at a
possibly-different commit) is not bit-identical to our local builds.

## 3. Host reproduction tooling (`scripts/repro_collect.sh`)

A portable, fusil-faithful collector — the only reliable way to reproduce the ~26
hold-outs is on the host, against the binary that found them.

- Mirrors fusil's invocation: `PYTHON_GIL`, `ASAN_OPTIONS=detect_leaks=0`, `python -u
  source.py`, cwd = source dir (see any crash dir's `replay.py` / `session.log`).
- Per build × GIL mode: full stdout/stderr, exit code, crash classification, **crash
  rate over N runs** (flakiness), gdb backtrace, resolved crash site.
- Configurable: `REPRO_BUILDS="name=/abs/python ..."`, `REPRO_RUNS=N`, `REPRO_GIL=0|1|both`.

Deploy on the fuzzing host:

```bash
REPRO_BUILDS="host=/home/ubuntu/projects/upstream_cpython/python" \
REPRO_GIL=0 REPRO_RUNS=10 \
  scripts/repro_collect.sh ~/crashers/python-7/multiprocessing_forkserver-segmentation_fault out/
```

`scripts/norepro_matrix.sh <labels.txt> <out-root>` drives it over a list and aggregates
which builds/GIL-modes reproduced + the sites discovered.

## Takeaway for the campaign

Triage fidelity is lost whenever repro happens on a build/host different from the one
that found the crash. The cheap structural fix is to capture a same-binary gdb
backtrace **at crash time on the host** (fusil already has the hooks — `replay.py` sets
`allow_core_dump=True`, `ptrace_program='gdb.py'`), so every crasher arrives pre-triaged
with a faithful site and we never re-litigate host↔local nondeterminism. For local
triage, sweep **build × GIL-mode**, direct-run first and gdb second.
