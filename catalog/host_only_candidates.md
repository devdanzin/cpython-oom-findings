# Host-only candidates

Crashes the fuzzing host hit (and fusil flagged `oomNEW`) that do **not** reproduce on
any local build, so they can't be confirmed/root-caused here. Recorded with their host
signature; reproduce on the host (`scripts/repro_collect.sh` pointed at the host binary)
to promote one to a full `OOM-####` report. OOM crash sites are binary/timing-specific
(see `catalog/norepro_investigation.md`), so "no local repro" ≠ "not a bug".

---

## HOC-1 — `tstate->current_frame` assertion via `concurrent.interpreters.list_all()` under OOM

- **Vehicle:** `~/crashers/concurrent_interpreters-assertion-sigabrt-oomNEW` (host `python-11`).
- **Assertion (host):** `Python/ceval.c:1216: _PyEval_EvalFrameDefault: Assertion
  `tstate->current_frame == NULL || tstate->current_frame == ...' failed.` → `Fatal Python error: Aborted`.
- **Host C-stack (named frames):** `_PyList_AppendTakeRefListResize` → `_Py_Dealloc` →
  `PyObject_CallFinalizerFromDealloc` → `PyObject_CallOneArg` → `_PyEval_EvalFrameDefault`.
- **Python trigger:** `concurrent.interpreters.list_all()` under the `set_nomemory` sweep.
- **Mechanism (hypothesis):** during a list append under OOM, an object is deallocated and
  its **finalizer runs Python code** (`PyObject_CallFinalizerFromDealloc` → eval) while the
  thread state's `current_frame` is in an inconsistent state — re-entering the eval loop
  mid-dealloc trips the frame-consistency assert. Plausibly free-threading-relevant (the
  host runs `PYTHON_GIL=0`) and/or subinterpreter-state specific.
- **Local repro:** **NOREPRO** on all four builds (`ft_debug_asan`, `ft_release`, `jit`,
  `upstream`), both GIL modes, 8+ attempts. Host-only on our binaries.
- **Next:** re-run on the host (same binary that found it) to capture a symbolized
  backtrace; if it reproduces there, promote to an `OOM-####` report.
