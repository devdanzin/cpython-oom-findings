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
  `upstream`), both GIL modes, 8+ attempts.
- **Why (diagnosed):** it is **gated by a commit, not by clang/timing.** Both host builds
  (FT `65afcdd8dfb`, JIT `fd53ae11391`) are *before* `ad1513a263b` ("GH-150516: Reduce the
  work done to spill and reload the stack around calls"); both local builds are *after* it,
  and reproduction tracks that boundary exactly. The assertion
  `assert(tstate->current_frame == NULL || tstate->current_frame->stackpointer != NULL)`
  (ceval.c:1216) is byte-identical across the commits, so the behavior — not the assert —
  changed: `ad1513a263b` reworks the stackpointer-around-calls machinery (adds
  `entry.frame.stackpointer_valid`) that the assertion guards. The clang difference
  (host 21.1.8 vs local 22.1.2) is incidental correlation.
- **Status:** **likely RESOLVED upstream by GH-150516 / `ad1513a263b`** (the trigger — a
  finalizer re-entering eval mid-dealloc while `stackpointer` is unset — is eliminated by
  the new validity tracking). Not minting an OOM-#### report. To confirm decisively, build
  the host commit `65afcdd8dfb` with clang-22 (isolating commit from compiler) and re-run.
- **General lesson:** when an OOM crasher doesn't reproduce on a newer build, diff the
  commit range first — a relevant `main` commit may have shifted/fixed it. This
  build-sensitivity is real and will bite anyone verifying OOM fixes.
