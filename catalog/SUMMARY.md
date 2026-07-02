# Fusil OOM-injection findings on CPython — summary

Snapshot: 2026-07-02 · CPython `main` 3.16.0a0 (commit `15d7406` for OOM-0001…0035, `1b9fe5c` for OOM-0036…0043) · **37 distinct bugs** (OOM-0001…0043; OOM-0005, OOM-0029, OOM-0033, OOM-0041 folded into OOM-0036; OOM-0011 folded into OOM-0008; OOM-0042 folded into OOM-0040).

**Method.** [Fusil](https://github.com/devdanzin/fusil) fuzzes CPython with `_testcapi.set_nomemory`
to fail allocations and drive the rarely-tested allocation-failure error paths. Crashes are triaged
and deduped by crash *site* across a 4-build matrix: free-threaded debug+ASan, free-threaded release,
JIT, and upstream release. One report per unique bug under `reports/OOM-####-*/` (each has `report.md`,
`repro.py`, `backtrace.txt`, `meta.json`, and the preserved fuzzer vehicle where minimization is partial).

**Legend**
- **Kind** — `segv` (SIGSEGV) · `abort` (SIGABRT, usually a `Py_DEBUG` assertion) · `fatal` (`Fatal Python error`).
- **Builds** — where it reproduces / how serious on a production build:
  - `release` — crashes a normal `-DNDEBUG` build (ft_release / upstream) → real production crash.
  - `ASan/jit` — only the ASan / JIT / debug builds catch it (a `Py_DEBUG` assert fires, or ASan flags
    UB); compiled-out or *latent* on a release build. Still a real bug (often a latent NULL-deref/UAF).
  - `debug` — observed on the free-threaded debug+ASan build.
- **MRE** — `yes`: a small, self-contained reproducer reliably triggers it. `no`: *vehicle-confirmed* —
  reproduces reliably from the generated fuzzer script (preserved in the report), but no reduced minimal
  trigger has been isolated yet. **`no` does not mean "irreproducible".**

| ID | Title | Kind | Builds | MRE | Site (file:func) |
|----|-------|------|--------|-----|------------------|
| OOM-0001 | warnings: over-decref of `filename` (unchecked `setup_context` alloc) | segv | release | yes | `_warnings.c:do_warn` |
| OOM-0002 | `contextvars.ContextVar.set` over-decref under OOM | segv | release | yes | `context.c:PyContextVar_Set` |
| OOM-0003 | `code_dealloc` asserts `co != NULL` (codeobject) | abort | debug | yes | `codeobject.c:code_dealloc` |
| OOM-0004 | list freelist clear / `PyList_New`→`free_list_items` dealloc | abort | debug | yes | `object.c:clear_freelist` |
| OOM-0006 | `dictiter_dealloc` dict-iterator dealloc under OOM | abort | release | yes | `dictobject.c:dictiter_dealloc` |
| OOM-0007 | `context_tp_dealloc` with a pending exception | fatal | ASan/jit | yes | `context.c:context_tp_dealloc` |
| OOM-0008 | type lookup leaves stale/missing exception; NDEBUG→latent NULL | abort | ASan/jit | yes | `typeobject.c:_PyType_LookupStackRefAndVersion` |
| OOM-0009 | `str.replace` ASCII→UCS widen desync under OOM | abort | ASan/jit | yes | `unicodeobject.c:replace` |
| OOM-0010 | eval frame: `profiling.sampling…dump_stack` under OOM | abort | debug | yes | `generated_cases.c.h:_PyEval_EvalFrameDefault` |
| OOM-0012 | instrumentation: `_co_monitoring` left NULL → release segv | abort | release | yes | `instrumentation.c:get_tools_for_instruction` |
| OOM-0013 | `CALL` specialization (builtin fast-with-kwargs) under OOM | abort | ASan/jit | yes | `ceval.c:_Py_BuiltinCallFastWithKeywords_StackRef` |
| OOM-0014 | `_interpchannels` channel-id alloc under OOM | abort | release | yes | `_interpchannelsmodule.c:channelsmod__channel_id` |
| OOM-0015 | `sys._baserepl`/`_clear_type_cache` kwargs check under OOM | abort | ASan/jit | yes | `methodobject.c:cfunction_check_kwargs` |
| OOM-0016 | `_interpqueues` queue alloc/clear under OOM | abort | ASan/jit | yes | `_interpqueuesmodule.c:_queue_clear` |
| OOM-0017 | free-threaded GC `gc_get_refs` assert (`array.array` type deferred-refcount drift via `socket.recv_fds`) | abort | ASan/jit | yes | `gc_free_threading.c:validate_gc_objects` |
| OOM-0018 | dict `set_keys`: `ClearManagedDict` OOM-recovery skips `ensure_shared_on_resize` | abort | debug | yes | `dictobject.c:set_keys` |
| OOM-0019 | negative refcount in pegen syntax-error path | abort | ASan/jit | yes | `pegen_errors.c:_PyPegen_raise_error_known_location` |
| OOM-0020 | `_interpreters.create(reqrefs=True)` threadstate free fatal | fatal | release | yes | `pystate.c:free_threadstate` |
| OOM-0021 | function returned a result with an exception set | fatal | ASan/jit | yes | `call.c:_Py_CheckFunctionResult` |
| OOM-0022 | slot succeeded with an exception set (extension reload) | fatal | ASan/jit | yes | `call.c:_Py_CheckSlotResult` |
| OOM-0023 | pure-Python type dealloc with pending exc (argparse/urllib/logging) | fatal | debug | yes | `object.c:_Py_Dealloc` |
| OOM-0024 | t-string `template_iter` frees uninitialized iterator → UAF | segv | ASan/jit | yes | `templateobject.c:templateiter_clear` |
| OOM-0025 | `unspecialize` with a pending exception under OOM | abort | ASan/jit | yes | `specialize.c:unspecialize` |
| OOM-0026 | `_interpchannels` int-error vs `PyErr` desync | abort | ASan/jit | yes | `_interpchannelsmodule.c:handle_channel_error` |
| OOM-0027 | `POP_JUMP_IF_FALSE` non-bool stackref assert | abort | ASan/jit | yes | `generated_cases.c.h:_PyEval_EvalFrameDefault` |
| OOM-0028 | `os._path_normpath(bytes)` → unchecked encode → NULL deref | segv | release | yes | `unicodeobject.c:unicode_encode_utf8` |
| OOM-0030 | `str` subclass instantiation frees a unicode with NULL data | abort | ASan/jit | yes | `unicodeobject.c:unicode_is_singleton` |
| OOM-0031 | `_interpreters.capture_exception` frees an invalid cross-interp excinfo → UAF | segv | release | yes | `crossinterp.c:_excinfo_clear_type` |
| OOM-0032 | warning emitted with a pending exception (`!_PyErr_Occurred`) | abort | ASan/jit | yes | `typeobject.c:type_call` / `object.c:PyObject_Str` |
| OOM-0034 | tokenizer col-offset: unchecked `PyUnicode_AsUTF8` → NULL deref | segv | release | yes | `pegen.c:_PyPegen_byte_offset_to_character_offset_line` |
| OOM-0035 | `StringIO.getvalue()` scans uninitialized buffer → bad `maxchar` | abort | ASan/jit | yes | `unicodeobject.c:_PyUnicode_FromUCS4` |
| OOM-0036 | `list.append(x)` under `MemoryError` double-frees the item (`_CALL_LIST_APPEND` steals `arg`, then `ERROR_NO_POP`) | abort | release | yes | `bytecodes.c:_CALL_LIST_APPEND` |
| OOM-0037 | unraisable reporter derefs NULL `UnraisableHookArgs` type-dict finalizing a failed sub-interpreter | segv | release | yes | `errors.c:make_unraisable_hook_args` / `structseq.c:get_type_attr_as_size` |
| OOM-0038 | sub-interpreter TLBC-index reserve calls `PyErr_NoMemory()` with no active thread state (FT-only) | fatal | release | yes | `index_pool.c:_PyIndexPool_AllocIndex` |
| OOM-0039 | `deque_clear`'s `newblock`-failure `PyErr_Clear()` clobbers an in-flight exception when run from `deque_dealloc` under OOM | fatal | ASan/jit | yes | `_collectionsmodule.c:deque_clear` / `deque_dealloc` |
| OOM-0040 | extensions-cache key-alloc failure under OOM mishandled — NULL cache key → `strlen(NULL)` segv (SET path), and a stale `MemoryError` → post-init `assert(!PyErr_Occurred())` abort (GET path, was OOM-0042) | segv | release | no | `import.c:hashtable_hash_str` / `_extensions_cache_set` / `import_run_extension` |
| OOM-0043 | `_blake2` `.copy()` under OOM decrefs a half-built object whose `impl` was never set → `py_blake2_clear` switches on garbage → `Py_UNREACHABLE` (raw-`malloc` failure; found by fusil `--oom-foreign`) | fatal | release | yes | `blake2module.c:py_blake2_clear` / `_blake2_blake2b_copy_impl` |

*(OOM-0041 was retired — folded into OOM-0036; OOM-0042 was retired — folded into OOM-0040; see "Retired IDs" below.)*

**Totals:** 37 bugs — 8 segv, 21 abort, 8 fatal · 13 reproduce on a **release** build · **36 of 37 have a
minimal reproducer** (OOM-0040 is vehicle-confirmed, minimization partial; OOM-0043's repro needs a
raw-`malloc` fault injector — an `LD_PRELOAD` shim, not `_testcapi` — see its report). Six retired ids: OOM-0005,
OOM-0029, OOM-0033, OOM-0041 → OOM-0036 (rr-proven faces of the `_CALL_LIST_APPEND` double-free), OOM-0011 →
OOM-0008 (rr-proven `f_back`-swallow detector face), and OOM-0042 → OOM-0040 (rr-proven GET-path face of the
extensions-cache key-alloc failure).

**Upstream status** (refreshed 2026-07-02 from the umbrella [#151763](https://github.com/python/cpython/issues/151763) table + timeline; per-report truth is each `meta.json` `upstream_issue`/`status`). **15 findings filed upstream**, 4 already **fixed**:
- **Fixed:** OOM-0002 (#151773), OOM-0003 (#152034 + 3.13/3.14/3.15 backports), OOM-0028 (#152058), OOM-0031 (#151842).
- **Filed, open:** OOM-0001 (#151673), OOM-0006 (#152107, dict item-iter — our sub-issue, repro_direct.py contributed + acked), OOM-0007 (#152083), OOM-0013 (#151968 PR), OOM-0014 (#151902 PR), OOM-0016 (#152130), OOM-0019 (#151931 PR), OOM-0024 (#151815), OOM-0034 (#151798 PR), OOM-0036 (#151818), OOM-0043 (#152851, `_blake2` copy-under-OOM — first `--oom-foreign` find).
- **Filing-hold** (FT sub-interpreter category, [#143232](https://github.com/python/cpython/issues/143232)): OOM-0020, OOM-0038.
- **New, drafted (not yet filed):** OOM-0037, OOM-0040 (now also covers the former OOM-0042 abort face).
- **Retired ids** (folded into another bug, not reused): OOM-0005, OOM-0029, OOM-0033, OOM-0041 → OOM-0036 (rr-proven faces of the `_CALL_LIST_APPEND` list.append double-free, via different stdlib paths); OOM-0011 → OOM-0008 (rr-proven: same `PyFrame_GetBack` f_back-swallow `MemoryError`, caught at the LOAD_ATTR-specialize assert instead of the type-cache assert); OOM-0042 → OOM-0040 (rr-proven: same extensions-cache key-alloc failure in `_extensions_cache_find_unlocked`, caught at the GET-path post-init `import_run_extension:2301` assert instead of the SET-path NULL-key segv).
- The rest remain gisted/novel. Two upstream issues without a gist link — [#151905](https://github.com/python/cpython/issues/151905) (`_PyType_LookupStackRefAndVersion` assert, closed) and [#152125](https://github.com/python/cpython/issues/152125) (`clear_freelist` freelist corruption, open) — are unmapped to our catalog (may be others' or need triage).

**Suggested starting points** — crashes a release build **and** has a minimal reproducer (highest
confidence, lowest effort to verify): **OOM-0001, 0002, 0012, 0014, 0020, 0028, 0031, 0034, 0038**. Of these,
**OOM-0034** and **OOM-0028** are the cleanest single-defect unchecked-allocation NULL derefs (≈one-line fixes);
**OOM-0038** is similarly clean (drop a `PyErr_NoMemory()` call), but free-threaded-only.
(**OOM-0036** is the most severe memory-safety defect — a `list.append`-under-`MemoryError`
double-free that crashes a release build; the eval-loop stackref over-decref formerly tracked as
OOM-0005 turned out to be a downstream face of it, see Retired IDs.)

**Sibling clusters (why some vehicles resist primitive reduction).** Several findings sit on
tightly-coupled C error paths: reducing a vehicle to primitives often just re-routes the failure
to a *neighbouring* bug, because the vehicle's specific allocation profile selects which sibling
fires. Three observed clusters:
- **pegen error-recovery** — OOM-0013 (`ceval.c:843`, CALL specialize result/error contract),
  OOM-0019 (`pegen_errors.c` error-line double-free), OOM-0021 (`call.c:43` `_Py_CheckFunctionResult`
  NULL). `compile()` / `ast.parse` / direct-builtin paths each trip a different one, so `ast.parse`
  is the natural readable entry for OOM-0019 rather than an incidental vehicle.
- **stale-pending-`MemoryError`** — these are `!PyErr_Occurred()` / "succeeded-with-exception"
  **detector** asserts; the real defect is elsewhere and **not on the crash stack** (it has already
  returned), so these can only be disambiguated by `rr`. Two sub-classes: a *swallowed* producer
  (an alloc fails and the `MemoryError` is left unpropagated — OOM-0008, OOM-0040), or a
  *cleanly-raised* `MemoryError` whose **consumer** then runs an object slot / de-opt without
  clearing it (OOM-0022, OOM-0025). Known producers: **OOM-0008** = `PyFrame_GetBack` swallows a
  `MemoryError` reading `frame.f_back` — caught at the type-cache assert (`typeobject.c:6343`) *and*
  the LOAD_ATTR-specialize assert (`specialize.c:364`); the retired OOM-0011 was that second face
  (`rr`-folded). A second producer is the **extensions-cache key-alloc failure** (OOM-0040):
  `_extensions_cache_find_unlocked`'s key `PyMem_RawMalloc` fails under OOM and is returned as a
  plain NULL; on the GET path it leaves a stale `MemoryError` that trips `import_run_extension:2301`
  — the retired OOM-0042 was that abort face (`rr`-folded into OOM-0040, whose SET path segfaults on
  the same NULL key). Still distinct (producer rr-checked, kept separate): **OOM-0025**
  (`specialize.c:378` `unspecialize`; producer = `PyImport_AddModuleRef`→`PyUnicode_New` in
  `sys._baserepl` setup, the LOAD_GLOBAL specializer merely inherits it — a *cleanly-raised*
  `MemoryError`, the bug is the de-opt path's intolerance of it) and **OOM-0022**
  (`_Py_CheckSlotResult`, single-phase extension reload; producer rr-confirmed =
  `_modules_by_index_set`'s `PyList_Append`→`list_resize` (`import.c:590`/`import.c:2010`), again
  a *cleanly-raised* `MemoryError`, the bug is the L2011 cleanup `PyMapping_DelItem` running the
  dict `__delitem__` slot without saving/clearing it). Both are the inverse of OOM-0008's
  swallow: the producer is well-behaved, the *consumer* (specializer de-opt / cleanup delete)
  fails to tolerate a pending exception.
- **dealloc-clears / over-decref `MemoryError`** — OOM-0007 & OOM-0023 (a `tp_dealloc` clears an
  in-flight `MemoryError`: dedicated `context_tp_dealloc` vs generic `subtype_dealloc`), OOM-0029
  (an over-decref leaves a refcount-0 `MemoryError`, caught at tuple teardown), and
  OOM-0036 (the `_CALL_LIST_APPEND` `list.append` double-free under `MemoryError`). OOM-0036 is a
  vivid example of "one producer, many detectors": `rr` reverse-execution pinned the
  formerly-separate **OOM-0041** (`traceback.c:313`), **OOM-0005** (`frame.c:101` negref /
  `pycore_stackref.h:726` / `PyOS_FSPath` SEGV) and **OOM-0033** (`list_ass_slice` negref /
  `PyType_IsSubtype` release SEGV) and **OOM-0029** (`_pyrepl.utils.disp_str` → `tuple_dealloc` negref) — plus the `tuple_alloc` freelist SEGV face — all to OOM-0036's
  double-freed appended item, reused and then read by whichever invariant gets there first. All
  three reached the same append-machinery `_CALL_LIST_APPEND` via different stdlib paths and were
  folded into OOM-0036.

A vehicle that looks "incidental" is often load-bearing precisely because its allocation count lands
the failure on the intended sibling rather than a neighbour. **`rr` reverse-execution** (record the
crash, watchpoint the victim, `reverse-continue` to the freeing decref) is the tool that turns these
"detector face" guesses into a pinned producer — it is what linked OOM-0041 → OOM-0036.

Notes:
- The `ASan/jit` rows are mostly `Py_DEBUG` assertions compiled out under `-DNDEBUG`; several reports note
  the release behavior is then a *latent* NULL-deref/UB rather than a clean crash (e.g. OOM-0008, OOM-0012).
- This file is a curated snapshot. Per-bug detail (full backtrace, root cause, suggested fix, reproducer,
  build matrix) is in each `reports/OOM-####-*/`; `INDEX.md` is the auto-generated full listing.
