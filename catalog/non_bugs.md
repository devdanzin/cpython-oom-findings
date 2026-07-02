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
