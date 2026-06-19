# Fusil OOM-injection findings on CPython — summary

Snapshot: 2026-06-19 · CPython `main` 3.16.0a0, commit `15d7406` · **35 distinct bugs** (OOM-0001…0035).

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
| OOM-0005 | eval stackref `PyStackRef_XCLOSE` over-decref | abort | release | yes | `pycore_stackref.h:PyStackRef_XCLOSE` |
| OOM-0006 | `dictiter_dealloc` dict-iterator dealloc under OOM | abort | release | yes | `dictobject.c:dictiter_dealloc` |
| OOM-0007 | `context_tp_dealloc` with a pending exception | fatal | ASan/jit | yes | `context.c:context_tp_dealloc` |
| OOM-0008 | type lookup leaves stale/missing exception; NDEBUG→latent NULL | abort | ASan/jit | yes | `typeobject.c:_PyType_LookupStackRefAndVersion` |
| OOM-0009 | `str.replace` ASCII→UCS widen desync under OOM | abort | ASan/jit | yes | `unicodeobject.c:replace` |
| OOM-0010 | eval frame: `profiling.sampling…dump_stack` under OOM | abort | debug | yes | `generated_cases.c.h:_PyEval_EvalFrameDefault` |
| OOM-0011 | `LOAD_ATTR` specialization under OOM | abort | ASan/jit | yes | `specialize.c:specialize` |
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
| OOM-0029 | negative refcount (over-decref) on `MemoryError` path (`disp_str`) | abort | ASan/jit | yes | `tupleobject.c:tuple_dealloc` |
| OOM-0030 | `str` subclass instantiation frees a unicode with NULL data | abort | ASan/jit | yes | `unicodeobject.c:unicode_is_singleton` |
| OOM-0031 | `_interpreters.capture_exception` frees an invalid cross-interp excinfo → UAF | segv | release | yes | `crossinterp.c:_excinfo_clear_type` |
| OOM-0032 | warning emitted with a pending exception (`!_PyErr_Occurred`) | abort | ASan/jit | yes | `typeobject.c:type_call` / `object.c:PyObject_Str` |
| OOM-0033 | import over-decrefs a `sys.path` entry → freed-obj `isinstance` | segv | release | yes | `typeobject.c:PyType_IsSubtype` |
| OOM-0034 | tokenizer col-offset: unchecked `PyUnicode_AsUTF8` → NULL deref | segv | release | yes | `pegen.c:_PyPegen_byte_offset_to_character_offset_line` |
| OOM-0035 | `StringIO.getvalue()` scans uninitialized buffer → bad `maxchar` | abort | ASan/jit | yes | `unicodeobject.c:_PyUnicode_FromUCS4` |

**Totals:** 35 bugs — 7 segv, 23 abort, 5 fatal · 11 reproduce on a **release** build · **all 35 have a
minimal reproducer** (0 vehicle-confirmed).

**Upstream status** (issue-tracker check 2026-06-19, see `catalog/prior_art.md`): only **OOM-0001** is already filed — [#151673](https://github.com/python/cpython/issues/151673) (open). The other 34 have no matching python/cpython issue (appear novel).

**Suggested starting points** — crashes a release build **and** has a minimal reproducer (highest
confidence, lowest effort to verify): **OOM-0001, 0002, 0005, 0012, 0014, 0020, 0028, 0031, 0033, 0034**. Of these,
**OOM-0034** and **OOM-0028** are the cleanest single-defect unchecked-allocation NULL derefs (≈one-line fixes);
**OOM-0005** is the most severe (a genuine eval-loop stackref over-decref → use-after-free on release).

Notes:
- The `ASan/jit` rows are mostly `Py_DEBUG` assertions compiled out under `-DNDEBUG`; several reports note
  the release behavior is then a *latent* NULL-deref/UB rather than a clean crash (e.g. OOM-0008, OOM-0012).
- This file is a curated snapshot. Per-bug detail (full backtrace, root cause, suggested fix, reproducer,
  build matrix) is in each `reports/OOM-####-*/`; `INDEX.md` is the auto-generated full listing.
