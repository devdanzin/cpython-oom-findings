# Crash report

### What happened?

Allocation-failure fuzzing of CPython `main` turned up **35 distinct ways the interpreter
crashes** — segfault, failed `assert(...)`, or `Py_FatalError` — when a memory allocation
fails part-way through an operation. Each is a separate underlying bug with a minimal,
stdlib-only reproducer, a backtrace, a root-cause analysis, and a suggested fix, published
as a self-contained gist (linked below).

I'm filing them under one umbrella so they can be picked off individually without flooding
the tracker with 35 issues at once. **To take one:** open a normal CPython issue (or PR) for
it and drop a comment here with the link — I'll mark it in the table. If any turn out to be
duplicates or non-bugs, say so and I'll annotate them.

These were found with [fusil](https://github.com/devdanzin/fusil)'s OOM-injection mode
(fusil originally by @vstinner). The reports and reduced reproducers were drafted with
AI assistance (Claude Code) and then reviewed and re-verified by hand — see *Disclosure*.

## Reproducing

- Found on `main` (3.16.0a0) at commit `15d7406`. These are allocation-path bugs, so they
  are not tied to that exact revision.
- Every gist ships a minimal `OOM-ID-repro.py` (standard library only) that drives the failing path
  while `_testcapi.set_nomemory(...)` forces allocations to fail. Just run **`python
  OOM-ID-repro.py`** — where the exact failing-allocation index is sensitive to the build's
  allocation count, the repro *self-sweeps* (a fresh subprocess per index) and stops at the
  first crash, so no manual tuning is needed.
- `_testcapi.set_nomemory` requires a test/debug interpreter (`--with-pydebug` exposes it).
- **Build matrix** (in each report): many of these are debug-only assertion / `Py_FatalError`
  failures — the `assert(...)` is compiled out under `-DNDEBUG`, so a *release* build doesn't
  abort. They are still real bugs: on release the same defect is latent undefined behaviour
  (a use-after-free, a `Py_DECREF(NULL)`, or a silently-lost exception). A subset segfault on
  release builds directly; those are called out below.

## Highest-confidence starting points

These crash a **release** build (not just a debug assertion) **and** have a clean minimal
reproducer — the lowest-effort to confirm and fix:

- **OOM-0034**, **OOM-0028** — unchecked `PyUnicode_AsUTF8` / `PyUnicode_EncodeFSDefault`
  returning `NULL` is dereferenced (≈ one-line NULL checks).
- **OOM-0001**, **OOM-0002**, **OOM-0014** — `Py_DECREF(NULL)` on an unchecked-allocation
  error path.
- **OOM-0031** — `_interpreters.capture_exception` calls `_PyXI_FreeExcInfo(NULL)` with no
  NULL guard.
- **OOM-0033** — a module import under OOM over-decrefs a `sys.path` entry.
- **OOM-0012**, **OOM-0020** — instrumentation / thread-state corruption under OOM.

## Findings

Status: blank = not yet filed · `#N` = a CPython issue is open.

### Segfaults (7)

| Report | Title | Status |
|---|---|---|
| [OOM-0001](https://gist.github.com/devdanzin/464cef74ca8186843f33a38078476ac4) | Segfault: `Py_DECREF` of a NULL `filename` in `do_warn` (`_warnings.c:1139`) | [#151673](https://github.com/python/cpython/issues/151673) |
| [OOM-0002](https://gist.github.com/devdanzin/2dfeabe7508f8e98f27f6df7e381f1cf) | Segfault: `Py_DECREF(NULL)` in `PyContextVar_Set` (`context.c:367`) | |
| [OOM-0024](https://gist.github.com/devdanzin/acf15ad4117c6343b48ed8fdfe7ad167) | Segfault: dealloc of uninitialized iterator in `template_iter` (`templateobject.c:232`) | |
| [OOM-0028](https://gist.github.com/devdanzin/774867b89b3de8d36d7e2ac405034577) | Segfault: NULL deref in `os__path_normpath_impl` (`posixmodule.c:6149`) | |
| [OOM-0031](https://gist.github.com/devdanzin/44ffdf25538575e497fd80552ea5d467) | Segfault: NULL `info` deref in `_excinfo_clear_type` (`crossinterp.c:1319`) | |
| [OOM-0033](https://gist.github.com/devdanzin/249032e1746d63406a5f68d7dfdedb79) | Segfault / negative-refcount: over-decreffed `sys.path` entry in `PyType_IsSubtype` (`typeobject.c:2931`) | |
| [OOM-0034](https://gist.github.com/devdanzin/9871a21facf4c9c6a415e220f9d10762) | Segfault: unchecked `PyUnicode_AsUTF8` NULL deref in `pegen.c:33` | |

### Assertion failures / aborts (23)

| Report | Title | Status |
|---|---|---|
| [OOM-0003](https://gist.github.com/devdanzin/b628c59722820b55c61a400a973771d5) | Abort: uninitialized `_co_unique_id` assert in `code_dealloc` (`codeobject.c:2440`) | |
| [OOM-0004](https://gist.github.com/devdanzin/315e83b2da6a5809ce5ae1d748cdd0ae) | Abort/Segfault: corrupted object freelist in `clear_freelist` (`object.c:909`) | |
| [OOM-0005](https://gist.github.com/devdanzin/22b71f61343c81df5bea9b7fca798e87) | Abort: negative-refcount over-decref in `_PyFrame_ClearLocals` (`frame.c:101`) | |
| [OOM-0006](https://gist.github.com/devdanzin/c809eb4072c0c787c0c890f54ba1c843) | Abort/Segfault: `_PyObject_GC_UNTRACK` assert on untracked iterator in `dictiter_dealloc` (`dictobject.c:5532`) | |
| [OOM-0008](https://gist.github.com/devdanzin/3c6690d0561acc62752a953e12b20197) | Abort: `assert(!PyErr_Occurred())` in `_PyType_LookupStackRefAndVersion` (`typeobject.c:6343`) | |
| [OOM-0009](https://gist.github.com/devdanzin/34b633230f6d2301ba17dec195ffe4b7) | Abort: stale `release1` flag trips an ownership assert in `replace` (`unicodeobject.c:10783`) | |
| [OOM-0010](https://gist.github.com/devdanzin/d3c1d06e95c006a320dbbfffcc210d52) | Abort: `assert(_PyErr_Occurred(tstate))` in `_PyEval_EvalFrameDefault` (`generated_cases.c.h:13817`) | |
| [OOM-0011](https://gist.github.com/devdanzin/892b61619c1b3c8c2018331b3f1f4983) | Abort: `assert(!PyErr_Occurred())` in `specialize` (`specialize.c:364`) | |
| [OOM-0012](https://gist.github.com/devdanzin/610c147c8e2d42a576bab3c1c2713391) | Abort/Segfault: stale instrumentation in `get_tools_for_instruction` (`instrumentation.c:1106`) | |
| [OOM-0013](https://gist.github.com/devdanzin/1736971107bea3aa04ce19db21c90845) | Abort: builtin breaks result/error contract in `_Py_BuiltinCallFastWithKeywords_StackRef` (`ceval.c:843`) | |
| [OOM-0014](https://gist.github.com/devdanzin/ceb4b16662d22b3dcb1b56cd8481c9e7) | Abort/Segfault: unchecked NULL in `channelsmod__channel_id` (`_interpchannelsmodule.c:3487`) | |
| [OOM-0015](https://gist.github.com/devdanzin/d40d39e6abfb746bd9d96de261205190) | Abort: stale exception in `cfunction_check_kwargs` (`methodobject.c:409`) | |
| [OOM-0016](https://gist.github.com/devdanzin/05be8efe6b08c2b3ac3e2c17c784da0c) | Abort: `assert(!queue->alive)` in `_queue_clear` (`_interpqueuesmodule.c:559`) | |
| [OOM-0017](https://gist.github.com/devdanzin/6e7a3a9487689e55d7dd4f70b1ce489f) | Abort: negative `gc_refs` ("refcount too small") in `validate_gc_objects` (`gc_free_threading.c:1116`) | |
| [OOM-0018](https://gist.github.com/devdanzin/99b84915b197ae0ade7face262b8af66) | Abort: ownership assert in `set_keys` (`dictobject.c:205`) | |
| [OOM-0019](https://gist.github.com/devdanzin/9bd9423256ea03c08231d1ebe542db89) | Abort: double-free in `_PyPegen_raise_error_known_location` (`pegen_errors.c:363`) | |
| [OOM-0025](https://gist.github.com/devdanzin/3aaffc18b68ca2ae5fffa72aa6cdb2ea) | Abort: `assert(!PyErr_Occurred())` in `unspecialize` (`specialize.c:378`) | |
| [OOM-0026](https://gist.github.com/devdanzin/bf6f784d4bcd21acd471ea45b6f23c70) | Abort: err-code vs `PyErr` desync in `handle_channel_error` (`_interpchannelsmodule.c:398` / `:443`) | |
| [OOM-0027](https://gist.github.com/devdanzin/d5c602c29ac3881290269b444d77db3c) | Abort: `assert(PyStackRef_BoolCheck(cond))` in `POP_JUMP_IF_FALSE` (`generated_cases.c.h:11120`) | |
| [OOM-0029](https://gist.github.com/devdanzin/10e0fdaf3d89dbe394d94fbf765c70a1) | Abort: negative refcount on a `MemoryError` (`tuple_dealloc`, `tupleobject.c:277`) | |
| [OOM-0030](https://gist.github.com/devdanzin/fbfb9d6cd5eeb518e4f9eeab44be3893) | Abort: `Py_DECREF` of NULL-data unicode in `unicode_subtype_new` (`unicodeobject.c:13986`) | |
| [OOM-0032](https://gist.github.com/devdanzin/f7e483080647c7b76fbda79bfeb07e9c) | Abort: pending-exception assert from `warn_explicit` normalization (`_warnings.c:799/806`) | |
| [OOM-0035](https://gist.github.com/devdanzin/8c86ca358f3711740a692eaac730b527) | Abort / malformed str: invalid `maxchar` in `_PyUnicode_FromUCS4` (`unicodeobject.c:2228`) | |

### Fatal Python error (5)

| Report | Title | Status |
|---|---|---|
| [OOM-0007](https://gist.github.com/devdanzin/bf9fec4554c58c2a279b05b7ff8e6d9b) | Fatal: `context_tp_dealloc` clears the pending exception (`context.c:535`) | |
| [OOM-0020](https://gist.github.com/devdanzin/df523c79368baa0c44bd69e9d5ee0c7e) | Fatal: `_PyMem_DebugRawFree: bad ID` in `free_threadstate` (`pystate.c:1527`) | |
| [OOM-0021](https://gist.github.com/devdanzin/e113c48a4e249ae7e4d1e42020db65c4) | Fatal: NULL returned without an exception set in `_Py_CheckFunctionResult` (`call.c:43`) | |
| [OOM-0022](https://gist.github.com/devdanzin/0964a71a7038ee90137f11c2527aad3c) | Fatal: stale `MemoryError` trips `_Py_CheckSlotResult` in `reload_singlephase_extension` (`import.c:2011`) | |
| [OOM-0023](https://gist.github.com/devdanzin/dc5123e50ea0402292e841411a294d3d) | Fatal: dealloc clears the in-flight exception in `subtype_dealloc` (`typeobject.c:2719`) | |

## Related groups (one fix may cover several)

- **Dealloc clears the in-flight exception** (the gh-89373 `_Py_Dealloc` invariant): **OOM-0007**
  (`context_tp_dealloc`) and **OOM-0023** (the generic `subtype_dealloc`, covering a family of
  pure-Python types) free an object while a `MemoryError` is pending and don't save/restore it.
- **A pending exception survives into code that asserts there is none** (specializer / eval /
  call layers): **OOM-0008, 0010, 0011, 0015, 0025, 0032**. Several share the theme that the
  adaptive specializer / call machinery is entered with a `MemoryError` already pending.
- **`Py_DECREF`/`Py_CLEAR` of a NULL or partially-initialized object on the OOM error path:**
  **OOM-0001, 0002, 0006, 0014, 0024, 0030, 0031** (an allocation fails after a slot is taken
  but before the object is valid, and the error path frees it anyway).
- **Over-decref → negative refcount under OOM** (a real memory-safety bug; the assert is the
  debug-build detector): **OOM-0005, 0019, 0029, 0033**.
- **Free-threading-specific:** **OOM-0003** (`_co_unique_id`), **OOM-0017** (cyclic GC),
  **OOM-0018** (managed dict), **OOM-0020** (thread-state reservation).

## Disclosure & caveats

- The reports and reduced reproducers were **drafted with AI assistance (Claude Code)**; each
  gist carries an explicit disclaimer. The reproducers were re-run on the build matrix and the
  root causes audited against the CPython source before publishing.
- A few root causes are explicitly marked **partial** — the trigger is minimal and verified,
  but the exact offending line wasn't pinned (noted in those reports): OOM-0010, 0027, 0029,
  0033, 0035.
- **OOM-0001** is already filed as
  [#151673](https://github.com/python/cpython/issues/151673); the other 34 had no matching
  python/cpython issue when checked and appear novel.

---

*Found with [fusil](https://github.com/devdanzin/fusil) (OOM-injection mode; fusil originally
by Victor Stinner). Drafted with Claude Code; reproducers machine-generated and human-verified.*


### CPython versions tested on:

CPython main branch

### Operating systems tested on:

Linux

### Output from running 'python -VV' on the command line:

Python 3.16.0a0 free-threading build (heads/main:15d74068f3a, Jun 18 2026, 16:44:30) [Clang 22.1.2 (1ubuntu1)]
