# Non-bugs / not-yet-reproduced vehicles

## False alarms (environmental — not crashes)
Exit code 1 from `ModuleNotFoundError` (target module not installed), not a memory crash:
- `python-4/psutil-exitcode1` — psutil not installed
- `python-4/psutil__ntuples-exitcode1` — psutil not installed
- `python-4/psutil__ntuples-exitcode1-2` — psutil not installed
- `python-4/psutil__psutil_linux-exitcode1` — psutil not installed
- `python-4/uv-exitcode1` — uv not installed

## Did not reproduce on the local build matrix
Captured on a different build (`/home/ubuntu/...`); allocation timing differs, so the
exact failing `start` doesn't line up. Re-check if we get matching builds:
- `python-4/concurrent_interpreters__crossinterp-segmentation_fault`
- `python-4/fractions-segmentation_fault`
- `python-4/xml_etree_cElementTree-segmentation_fault`

## Harness artifact — `set_nomemory` global-allocator race vs fuzzer worker threads (free-threaded)
**Was the OOM-0033 candidate.** Not a CPython bug — a limitation of the OOM-injection harness.

- **Vehicle:** `fleet inst-05 python-2 _thread-segmentation_fault-oomNEW` (flagged `oomNEW`).
- **Repro:** loop the vehicle on the free-threaded build, `PYTHON_GIL=0` → SIGSEGV ~30% of
  runs; `PYTHON_GIL=1` → 0/15. `PYTHONHASHSEED` fixed-vs-random makes no difference (3/15 vs
  5/15) — it is a thread *scheduling* race, not allocation-sequence/hash sensitive.
- **Why it's invisible in stdout:** the fault corrupts the child-thread stack, so faulthandler
  prints `<Cannot show all threads while the GIL is disabled>` + empty C trace and ASan
  cascades into `AddressSanitizer: nested bug in the same thread` at a recurring wild address
  `0xffffe8bf8d4d0000` — no usable frames persist. The real site only appears under **live gdb**
  (gdb-on-`ft_release` caught it on try 1; gdb on `ft_debug_asan` perturbs the timing away).
- **Root cause:** the crash is *inside the `_testcapi` test hook*, `Modules/_testcapi/mem.c`
  (`hook_fmalloc:112` / `hook_ffree:139`), with `ctx == NULL`:

  ```
  #0  hook_ffree (ctx=0x0, ptr=...) at Modules/_testcapi/mem.c:139   # alloc=ctx=NULL -> deref
  #1  unicode_dealloc ...                                            # (or, other capture:)
  #0  hook_fmalloc (ctx=0x0, size=56) at Modules/_testcapi/mem.c:112
  ...  _PyErr_CreateException(AttributeError) -> PyTuple_FromArray -> gc_alloc -> hook_fmalloc
  #17 thread_run (boot_raw=...) at Modules/_threadmodule.c:388       # a fuzzer worker thread
  #18 pythread_wrapper ... #19 start_thread #20 clone3
  ```

  `set_nomemory` (`fm_setup_hooks`) installs `hook_f*` with `ctx = &FmHook.<domain>` and
  `remove_mem_hooks` (`fm_remove_hooks`) swaps them back — both via `PyMem_SetAllocator`, which
  is **process-global and not thread-safe**. The fuzzer toggles `set_nomemory`/`remove_mem_hooks`
  every sweep iteration on the main thread while fuzzer-spawned worker threads keep allocating;
  a worker reads the allocator fn-pointer and its `ctx` non-atomically and, mid-swap, calls the
  hook with a torn `ctx=0x0` → NULL deref. The GIL serialises the swap against allocations, so
  this only happens on free-threaded builds — hence GIL=0 only.
- **Takeaway for the campaign:** an *unresolvable* free-threaded OOM segv (GIL-disabled,
  empty faulthandler stack, ASan `nested bug`, child thread) is almost certainly this race, not
  a CPython bug. Confirm by catching it under gdb on `ft_release` — if the innermost frame is
  `hook_f*@Modules/_testcapi/mem.c`, it is the harness. (Potential fusil follow-up: classify a
  resolved `_testcapi/mem.c` hook site as `oomHARNESS` so the dedup engine auto-files these.)

## Known-intentional `Py_FatalError` (by design — WONTFIX-class)

### tracemalloc — `tracemalloc_realloc() failed to allocate a trace` (`Python/tracemalloc.c:615`)
**Was a fusil-fleet5 `oomNEW` candidate** (`inst-03 python tracemalloc-fatal_python_error-oomNEW`,
2026-07-02). No matching tracker issue, but the fatal is **deliberate and documented at the call
site** — not an unguarded/mishandled error path:

```c
if (ADD_TRACE(ptr2, new_size) < 0) {
    // Memory allocation failed. The error cannot be reported to the caller,
    // because realloc() already [has] shrunk the memory block and so removed bytes.
    // This case is very unlikely: a hash entry has just been released, so the hash
    // table should have at least one free entry.
    Py_FatalError("tracemalloc_realloc() failed to allocate a trace");
}
```

On the resize path `realloc` has already shrunk the block (bytes gone), so the failure genuinely
can't be propagated to the caller — the devs chose to fatal as the lesser evil. Their "very
unlikely" assumption (a hash slot was just freed, so ADD_TRACE should find room) only holds under
normal conditions; `--oom-fuzz`/`set_nomemory` fails **every** allocation, including the freed-slot
re-use, so we walk straight into the documented dead-end. Predates the 2023 GH-101520 core-move.

**Disposition: intended behavior, not actionable** — upstream would close as such. This is the
"tracemalloc can't trace its own allocation failure under total-OOM injection" class (the error
path is *handled*, deliberately, unlike the real finds where code assumed success and hit
UB/an assert). Skip; don't re-flag.

## `--oom-foreign-pythonmalloc`: glibc heap-corruption oomNEW = the over-decref family (NOT new; rr-confirmed)

**fusil-fleet6 (2026-07-02) ran `--oom-foreign` PLUS `--oom-foreign-pythonmalloc`** (routes CPython's
own PyMem allocations through the LD_PRELOAD malloc shim, i.e. `PYTHONMALLOC=malloc`). Of its 57
`oomNEW` candidates: ~40 (70%) are glibc heap-corruption aborts (`malloc(): unaligned tcache chunk
detected` ×33, `smallbin double linked list corrupted` ×4, `corrupted double` ×1) across 15 unrelated
modules; ~19 (33%) are the `_Py_NegativeRefcount` / `PyStackRef_CheckValid` stackref-teardown aborts.
**None are new.**

**rr-confirmed (2026-07-02), not a shim artifact.** Vehicle
`inst-01/python/importlib_resources__functional-fatal_python_error-oomNEW` (deterministic 3/3 under
`LD_PRELOAD=<shim> PYTHONMALLOC=malloc <debug-gil-nojit> source.py`). Three levels of `rr`
reverse-execution from the abort: detecting `malloc` (CPython building a traceback) pops a misaligned
chunk from tcache bin 2 → that chunk's `fd` was clobbered → the clobbering write is
`Py_DECREF_MORTAL(op)` ← **`PyStackRef_XCLOSE` @ `pycore_stackref.h:726`** ← `_PyFrame_ClearLocals`
(`frame.c:101`) ← `_PyFrame_ClearExceptCode` ← `clear_thread_frame` — the eval-loop operand-stack
**frame teardown** decref'ing an object under the propagating `MemoryError`. So the "heap corruption"
is a genuine CPython **over-decref / use-after-free**: an object is freed too early during frame
teardown, and because `PYTHONMALLOC=malloc` makes its memory a glibc chunk, the stale refcount write
lands in the tcache fd → glibc aborts.

**Key point:** `pycore_stackref.h:726` / `PyStackRef_XCLOSE` is *exactly* the known over-decref family
(OOM-0005 / OOM-0036) — the **same site** that surfaces as `_Py_NegativeRefcount: object has negative
ref count` in the non-pythonmalloc runs. The tcache-corruption aborts and the negref aborts are the
**same bug at the same site**, detected at two layers (glibc heap vs CPython negref assert). The
`PYTHONMALLOC=malloc` shim only routes the free to glibc; it is a tail-call passthrough, not the
corruptor (verified: toggling `PYTHONMALLOC=malloc` off on the identical vehicle removes the
corruption and gives a clean `_Py_CheckFunctionResult` OOM crash; fleet5's plain `--oom-foreign` had
**0** such corruptions).

**The 98 `oomSEGV` (fleet6 first run) are the same family too.** `ingest.py` over
`inst-*/python/*oomSEGV*` resolved every one from the faulthandler C stack and found **0 new sites**;
the top frames are all stackref-steal / dealloc detectors — 66 `_PyTuple_FromStackRefStealOnSuccess`,
16 `_Py_VectorCallInstrumentation_StackRefSteal`, plus `_PyTuple_Concat`,
`PyObject_CallFinalizerFromDealloc`/`_Py_Dealloc`, `PyErr_ResourceWarning`/`WarnEx`. An object on the
operand stack is over-decref'd/freed under OOM; the segv is where a stolen stackref is dereferenced —
the same over-decref bug as the tcache aborts and negref aborts, just a third detector face. (ingest
flags them "needs-gdb", but that won't help: they're generic stackref detectors needing rr to fold,
and the `--oom-foreign-pythonmalloc` vehicles need the shim/`PYTHONMALLOC` env that ingest's gdb
re-run doesn't set up.)

**Disposition: `--oom-foreign-pythonmalloc` yields NO new findings** — its entire `oomNEW`/`oomSEGV`
output is the pre-existing over-decref/UAF family via a noisier glibc-heap lens. Prefer plain
`--oom-foreign` (0 corruption, found OOM-0043). For a real UAF lens use the catalog's method — a
GIL+ASan build with `PYTHONMALLOC=malloc` (clean freed-by/allocated-by stacks) — not the LD_PRELOAD
shim. Don't re-flag `--oom-foreign-pythonmalloc` glibc-corruption/negref/stackref-segv candidates as new.
