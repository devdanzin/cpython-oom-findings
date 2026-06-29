#!/usr/bin/env python3
"""Ingest a pile of fuzzer run-dirs, dedupe them against the read-only catalog snapshot
(catalog/known_sites.tsv), and surface ONLY genuinely-new crash sites. This is the
single-writer merge step: instances (or a batch) feed their crash dirs in; known-bug
vehicles are tallied and prunable, new sites are flagged for a report. No shared mutable
state -- it only READS the snapshot.

Matching considers EVERY signal a crash offers and calls it known if ANY matches: all
assertions in stdout (glibc `Assertion `expr'` and CPython `Assertion "expr"` forms), a
specific `Fatal Python error: <msg>`, and -- for segvs / generic-assert fatals -- every
real CPython frame in the gdb backtrace (via --sites-cache or --gdb). Checking all signals
avoids false "new" labels when the resolved frame is a secondary/cascade site but an
earlier assertion or a deeper frame is a known bug. (Mirrors fusil's in-loop oom_dedup.)

Usage:
  ingest.py [globs...] [--snapshot F] [--sites-cache F] [--gdb] [--keep N] [--json F] [--jobs N]
  default globs: ~/crashers/python-*/*  and ~/crashers/*/   (dirs containing stdout)

Per-dir classification is CPU-bound (regex over each crash's stdout) and fully independent,
so it runs across processes by default (`--jobs`, default min(16, cpus-2)). `--jobs 1` is the
serial path; output is identical either way (results are reduced in input order). `--gdb`
forces serial -- gdb re-runs are heavyweight and OOM-timing-sensitive, not safe to fan out.
"""
import sys, os, re, json, glob, subprocess, collections, pathlib
import concurrent.futures as cf
import multiprocessing as mp

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = ROOT / "scripts"

# ---- arg parsing (minimal) ----
args = sys.argv[1:]
def opt(name, default=None, flag=False):
    if name in args:
        i = args.index(name)
        if flag:
            args.pop(i); return True
        return args.pop(i), args.pop(i)
    return default
SNAP = pathlib.Path(opt("--snapshot", (None, str(ROOT / "catalog" / "known_sites.tsv")))[1])
CACHE = opt("--sites-cache", (None, None))[1]
USE_GDB = opt("--gdb", flag=True)
KEEP = int(opt("--keep", (None, "0"))[1])
JSON_OUT = opt("--json", (None, None))[1]
JOBS = int(opt("--jobs", (None, "0"))[1])  # 0 = auto (min(16, cpus-2)); 1 = serial
globs = [a for a in args if not a.startswith("--")] or [
    os.path.expanduser("~/crashers/python-*/*"), os.path.expanduser("~/crashers/*/")]

# ---- stdout classification ----
# "<file>:<line>: [ret] <func>[(args)]: Assertion <q>expr<q>" -- glibc backticks OR CPython
# double-quotes, optional (args) list.
ASSERT = re.compile(r"([\w./+-]+\.(?:c|h)):(\d+):.*?\b(\w+)\s*(?:\([^)]*\))?\s*:\s*Assertion[ `\"]+([^`'\"\n\t]*)")
ASSERT2 = re.compile(r"([\w./+-]+\.(?:c|h)):(\d+):.*?Assertion[ `\"]+([^`'\"\n\t]*)")  # func-less fallback
FATAL = re.compile(r'Fatal Python error:\s*([^\n]+)')
SEGV = re.compile(r'AddressSanitizer: SEGV|Fatal Python error: Segmentation fault|Segmentation fault')
IMPORTERR = re.compile(r'(ModuleNotFoundError|ImportError):')
GENERIC_FATAL = ("_PyObject_AssertFailed", "_Py_NegativeRefcount")
SYM = re.compile(r', at ([A-Za-z_]\w+)\+0x')
SKIP = re.compile(r'^(___?interceptor\w*|__sanitizer\w*|__asan\w*|_Py_DumpStack|faulthandler\w*|_PyEval_EvalFrameDefault|_PyEval_Vector|PyEval_EvalCode|Py_RunMain|Py_BytesMain|pymain_\w+|_start|__libc_start\w*)$')
FRAME = re.compile(r'([A-Za-z_]\w+)@([\w./+-]+\.(?:c|h)):(\d+)')
# ASan/sanitizer frame already in stdout: "#5 0x.. in func /abs/.../Python/foo.c:123:4".
# Lets us read the real crash site off the crash's OWN backtrace -- no gdb re-run, so it's
# deterministic (a re-run can miss under a fresh hash seed / thread timing).
# Source path may be absolute+column (Clang: /abs/Objects/foo.c:68:9) or relative+no-column
# (GCC: Objects/foo.c:68); make the absolute prefix and the column optional so GCC-built
# ASan traces parse too (else they fall back to faulthandler's inlined C-stack and known
# bugs get mislabelled new). Mirrors oom_dedup._ASAN_FRAME.
ASAN_FRAME = re.compile(r'#\d+\s+0x[0-9a-fA-F]+\s+in\s+(\w+)\s+(?:\S*?/)?'
                        r'((?:Objects|Python|Modules|Include|Parser)/[\w./+-]+\.(?:c|h)):(\d+)')
NATIVE_SKIP = re.compile(r'^(fatal_error(_exit)?|_Py_FatalError\w*|_PyObject_AssertFailed'
                         r'|_Py_NegativeRefcount|_Py_DumpStack|faulthandler\w*'
                         r'|_Py_DumpExtensionModules'
                         # debug allocator free-time checks: detectors, not the defect -- the
                         # real site is the caller doing the bad free (free_list_items,
                         # free_threadstate, ...). Mirrors oom_dedup._BT_SKIP / gen_known_sites.
                         r'|_PyMem_DebugCheckAddress|_PyMem_DebugRawFree|_PyMem_DebugFree'
                         # _testcapi set_nomemory injection hooks + PyMem_/PyObject_ free/realloc
                         # wrappers: pass-through allocator plumbing between the debug checks and
                         # the real caller -- skip so a bad free resolves to free_list_items
                         # (OOM-0004), not hook_ffree/PyMem_Free (which read as oomNEW on GCC).
                         r'|hook_fmalloc|hook_fcalloc|hook_frealloc|hook_ffree'
                         r'|PyMem_Free|PyMem_RawFree|PyObject_Free|PyMem_Realloc|PyMem_RawRealloc|PyObject_Realloc'
                         # tracemalloc allocator hooks: pass-through layer present in every
                         # alloc/free while tracing is on -- same detector role, skip to the
                         # real caller (e.g. free_list_items = OOM-0004). NB the by-design
                         # `tracemalloc_realloc() failed to allocate a trace` fatal is matched
                         # by its message, not this frame, so skipping it here is safe.
                         r'|tracemalloc_(raw_)?(alloc|calloc|realloc|free))$')
# inlined refcount/atomic helpers (these headers) mask the real .c caller of a
# "DECREF a freed object" segv -- skip so the site is e.g. do_warn, not Py_DECREF.
NATIVE_SKIP_FILE = re.compile(r'(?:^|/)(?:refcount|pyatomic\w*|object)\.h$')


def extract_native_sites(text):
    """Real CPython frames from a live ASan backtrace in stdout, innermost first."""
    out = []
    for m in ASAN_FRAME.finditer(text):
        f = nf(m.group(2))
        if not NATIVE_SKIP.match(m.group(1)) and not NATIVE_SKIP_FILE.search(f):
            out.append("%s@%s:%s" % (m.group(1), f, m.group(3)))
    return out


# Funcs to skip when matching a faulthandler-only C stack (func names, innermost first):
# the asan/dump/eval/run plumbing + the alloc/free + assert detectors + the dealloc dispatch
# and refcount macros that wrap every dealloc. The first SURVIVING func the catalog keys by
# name is the crash site. Superset of SKIP + NATIVE_SKIP for the symbol-only case.
FH_SKIP = re.compile(
    r'^(___?interceptor\w*|__sanitizer\w*|__asan\w*|_Py_Dump\w*|faulthandler\w*'
    r'|_PyEval_EvalFrameDefault|_PyEval_EvalFrame|_PyEval_Vector|PyEval_EvalCode|_PyEval_Frame\w*'
    r'|Py_RunMain|Py_BytesMain|pymain_\w+|_start|__libc_start\w*|run_mod|run_eval_code_obj'
    r'|pyrun_\w*|_PyRun_\w*|clear_thread_frame|clear_gen_frame'
    r'|fatal_error\w*|_Py_FatalError\w*|_PyObject_AssertFailed|_Py_NegativeRefcount'
    r'|_Py_Dealloc|_Py_MergeZeroLocalRefcount|Py_X?DECREF|Py_X?INCREF|_Py_X?DECREF\w*'
    r'|_PyMem_Debug\w*|PyMem_\w*Free|PyObject_\w*Free|PyMem_\w*Realloc|PyObject_\w*Realloc'
    r'|hook_f\w+|tracemalloc_\w+)$'
)


def fh_match(text, snap):
    """Fallback for a SEGV/generic-fatal whose stdout has a faulthandler C stack (func names)
    but NO ASan ``#N ... file.c:line`` frames (so extract_native_sites is empty) and no gdb
    resolution. Match the innermost catalog-keyed func BY NAME. Returns (oids, func) or
    (set(), None)."""
    for fn in SYM.findall(text):  # faulthandler prints most-recent-call first
        if FH_SKIP.match(fn):
            continue
        hit = snap["funcname"].get(fn)
        if hit:
            return set(hit), fn
    return set(), None


def nf(f):
    return f.lstrip("./")


def all_asserts(text):
    """Every assertion in stdout as a list of (file, line, func|None, expr)."""
    out, seen = [], set()
    for m in ASSERT.finditer(text):
        key = (nf(m.group(1)), int(m.group(2)))
        out.append((key[0], key[1], m.group(3), m.group(4).strip()))
        seen.add(key)
    for m in ASSERT2.finditer(text):
        key = (nf(m.group(1)), int(m.group(2)))
        if key not in seen:
            out.append((key[0], key[1], None, m.group(3).strip()))
            seen.add(key)
    return out


# ---- snapshot matcher ----
def load_snapshot(path):
    by_func, by_assert, by_line = {}, {}, {}
    per_file_lines = collections.defaultdict(list)
    by_funcname = {}  # bare func name -> oids (for faulthandler-only stacks; see fh_match)
    by_msg, by_msgfam, kind_of = [], [], {}
    for line in pathlib.Path(path).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        oid, kind, kt, key = line.split("\t")
        kind_of[oid] = kind
        if kt == "func":
            by_func.setdefault(key, set()).add(oid)
            fn = key.rsplit(":", 1)[-1]  # "file:func" -> "func"
            if re.fullmatch(r"\w+", fn):  # clean ident only (skip combined "a/b/c(...)" keys)
                by_funcname.setdefault(fn, set()).add(oid)
        elif kt == "assert":
            by_assert.setdefault(key, set()).add(oid)
        elif kt == "msg":
            by_msg.append((key, oid))
        elif kt == "msgfam":
            by_msgfam.append((key, oid))
        elif kt == "line":
            f, ln = key.rsplit(":", 1); ln = int(ln)
            by_line.setdefault((f, ln), set()).add(oid)
            per_file_lines[f].append((ln, oid))
    return dict(func=by_func, assert_=by_assert, line=by_line, fl=per_file_lines,
                msg=by_msg, msgfam=by_msgfam, kind=kind_of, funcname=by_funcname)


def match(c, snap):
    """Match ONE candidate dict -> (set(oom_ids), how) or (empty, 'NEW')."""
    if c.get("assert_expr") and c.get("file"):
        hit = snap["assert_"].get(f"{c['file']}:{c['assert_expr']}")
        if hit:
            return hit, "assert"
    if c.get("fatal_msg"):
        cm = c["fatal_msg"]
        # Exact-ish msg keys (prefix either way; full msg, not [:30], so type-specific keys like
        # OOM-0007 'Context' vs OOM-0023 '_StoreAction' aren't conflated). LONGEST match wins so
        # the most specific type key beats a shorter/family one. Mirrors oom_dedup.match.
        exact = [(k, o) for k, o in snap["msg"] if cm.startswith(k) or k.startswith(cm)]
        if exact:
            maxlen = max(len(k) for k, _ in exact)
            return set(o for k, o in exact if len(k) == maxlen), "msg"
        # Family fallback: a substring identifying a bug family (e.g. the generic subtype_dealloc
        # 'cleared the current exception'), used only when no type-specific key matched -> a new
        # type dedups to the family instead of oomNEW.
        fam = set(o for sub, o in snap.get("msgfam", ()) if sub in cm)
        if fam:
            return fam, "msgfam"
    if c.get("file") and c.get("func"):
        hit = snap["func"].get(f"{c['file']}:{c['func']}")
        if hit:
            return hit, "func"
    if c.get("file") and c.get("line"):
        hit = snap["line"].get((c["file"], c["line"]))
        if hit:
            return hit, "line"
        for ln, oid in snap["fl"].get(c["file"], ()):
            if abs(ln - c["line"]) <= 12:
                return {oid}, "near"
    return set(), "NEW"


def frame_to_cand(site):
    m = FRAME.match(site)
    return dict(file=nf(m.group(2)), func=m.group(1), line=int(m.group(3)),
                assert_expr=None, fatal_msg=None) if m else None


# ---- sites cache (precomputed local segv sites: label -> (signal, site, fingerprint)) ----
def load_cache(path):
    cache = {}
    if path and os.path.exists(path):
        for line in open(path):
            f = line.rstrip("\n").split("\t")
            if len(f) >= 3:
                cache[f[0]] = (f[1], f[2], f[3] if len(f) > 3 else "")
    return cache


def resolve_chain(crash_dir, label, cache):
    """Return the gdb chain ['func@file:line', ...] for a segv, via cache or --gdb."""
    fp = None
    if label in cache:
        fp = cache[label][2] or cache[label][1]   # fingerprint, else single site
    elif USE_GDB:
        try:
            out = subprocess.run(["bash", str(HERE / "segv_worker.sh"), crash_dir],
                                 capture_output=True, text=True, timeout=240).stdout
            parts = out.strip().split("\t")
            if len(parts) >= 4:
                fp = parts[3] or parts[2]
        except Exception:
            fp = None
    return [s for s in (fp.split(";") if fp else []) if FRAME.match(s)]


# ---- bounded stdout reader ----
# OOM-verbose / runaway sessions can emit tens of MB of stdout (per-iteration `start=N`
# spew, or a long binary blob with no newlines). Reading the whole file makes the `.*?`
# classification regexes above catastrophically backtrack -- a single 67 MB stdout timed a
# whole batch out. The crash signature always lives at the HEAD (early asserts / import
# errors) and the TAIL (the Fatal/ASan backtrace that ends the process), never buried in
# the middle, so read a bounded head+tail. Safe for every signal the matcher uses, and
# orders of magnitude faster. Override via INGEST_STDOUT_HEAD / INGEST_STDOUT_TAIL (bytes).
STDOUT_HEAD = int(os.environ.get("INGEST_STDOUT_HEAD", 256 * 1024))
STDOUT_TAIL = int(os.environ.get("INGEST_STDOUT_TAIL", 1024 * 1024))
# Per-line cap: real signals (asserts, `Fatal Python error:`, ASan `#N ... file.c:line`)
# are all short lines; a multi-MB binary blob with no newlines is a single giant "line"
# that makes the `.*?` regexes backtrack catastrophically even after head+tail bounding.
# Truncating each line to a few KB keeps every real signal and kills the blowup.
STDOUT_LINE_CAP = int(os.environ.get("INGEST_STDOUT_LINE_CAP", 4096))

def _cap_lines(text):
    if STDOUT_LINE_CAP <= 0:
        return text
    return "\n".join(ln if len(ln) <= STDOUT_LINE_CAP else ln[:STDOUT_LINE_CAP]
                     for ln in text.split("\n"))

def read_stdout(path):
    """Read a crash stdout, bounding huge files to head+tail and capping line length
    (decoded, errors-replaced) so the classification regexes can't catastrophically
    backtrack on OOM-verbose spew or embedded binary."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size <= STDOUT_HEAD + STDOUT_TAIL:
            fh.seek(0)
            return _cap_lines(fh.read().decode("utf-8", "replace"))
        fh.seek(0)
        head = fh.read(STDOUT_HEAD)
        fh.seek(size - STDOUT_TAIL)
        tail = fh.read(STDOUT_TAIL)
    elided = size - STDOUT_HEAD - STDOUT_TAIL
    return _cap_lines(head.decode("utf-8", "replace")
                      + f"\n...[{elided} bytes elided by ingest read_stdout]...\n"
                      + tail.decode("utf-8", "replace"))


# ---- main ----
# ---- per-dir classification (pure; runs in a worker process) ----
# The snapshot/cache are loaded once per worker via the pool initializer (cheap, and
# avoids re-parsing argv in workers). Each call reads one crash's stdout, classifies it,
# and returns a (category, key, label) triple that main() reduces into the report dicts.
# category: "skip" | "other" | "known" | "ambiguous" | "needs_gdb" | "new".
_W_SNAP = None
_W_CACHE = None


def _worker_init(snap, cache):
    global _W_SNAP, _W_CACHE
    _W_SNAP, _W_CACHE = snap, cache


def classify_dir(d):
    """Classify a single run-dir against the worker's snapshot. Pure + independent."""
    snap, cache = _W_SNAP, _W_CACHE
    label = f"{os.path.basename(os.path.dirname(d))}/{os.path.basename(d)}"
    try:
        text = read_stdout(os.path.join(d, "stdout"))
    except OSError:
        return ("skip", None, label)
    asserts = all_asserts(text)
    fa = FATAL.search(text)
    fmsg = fa.group(1).strip() if fa else None
    has_segv = bool(SEGV.search(text))
    generic = bool(fmsg) and fmsg.startswith(GENERIC_FATAL)

    if not asserts and not has_segv and not fmsg:
        return ("other", "import" if IMPORTERR.search(text) else "clean", label)

    candidates = [dict(file=f, line=ln, func=fn, assert_expr=expr, fatal_msg=None)
                  for (f, ln, fn, expr) in asserts]
    if fmsg and not generic and not fmsg.lower().startswith(("segmentation", "aborted")):
        candidates.append(dict(file=None, line=None, func=None, assert_expr=None, fatal_msg=fmsg))

    chain = []
    if has_segv or generic or not asserts:
        # Prefer the native backtrace already in stdout (ASan/debug build) -- the actual
        # fault, deterministic, no re-run. Fall back to the cache / gdb re-run only when
        # stdout carries no parseable native frames.
        chain = extract_native_sites(text) or resolve_chain(d, label, cache)
        # Match only the resolved SITE (chain[0], innermost real frame). Deeper frames
        # are shared deallocator/eval plumbing that would over-match many bugs.
        if chain:
            cand = frame_to_cand(chain[0])
            if cand:
                candidates.append(cand)

    matched = set()
    for c in candidates:
        matched |= match(c, snap)[0]

    # Faulthandler-only fallback: a SEGV/generic-fatal with no ASan file:line frames and no
    # gdb resolution still carries func names in the faulthandler C stack -- match the
    # innermost catalog-keyed func by name (e.g. PyList_New -> OOM-0004) instead of giving up.
    if not matched and not chain and (has_segv or generic):
        matched |= fh_match(text, snap)[0]

    if matched:
        if len(matched) == 1:
            return ("known", next(iter(matched)), label)
        return ("ambiguous", "|".join(sorted(matched)), label)
    if (has_segv or generic) and not chain:
        coarse = (" <- ".join([s for s in SYM.findall(text) if not SKIP.match(s)][:3])
                  or (fmsg[:50] if fmsg else "(no-sym)"))
        return ("needs_gdb", coarse, label)
    prim = candidates[0] if candidates else {}
    key = (prim.get("assert_expr") and f"{prim['file']}:{prim['assert_expr']}") or \
          (prim.get("func") and f"{prim['file']}:{prim['func']}") or \
          prim.get("fatal_msg") or (chain[0] if chain else "?")
    kind = "abort" if asserts else ("segv" if has_segv else "fatal")
    return ("new", (kind, key), label)


def _resolve_jobs(n_dirs):
    """Pick worker count: explicit --jobs, else auto; serial for tiny batches or --gdb."""
    jobs = JOBS or min(16, max(1, (os.cpu_count() or 2) - 2))
    if USE_GDB or n_dirs < 256:
        return 1
    return jobs


def main():
    snap = load_snapshot(SNAP)
    cache = load_cache(CACHE)
    dirs = []
    for g in globs:
        for p in glob.glob(g):
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "stdout")):
                dirs.append(p)
    dirs = sorted(set(dirs))

    known = collections.defaultdict(list)
    ambiguous = collections.defaultdict(list)
    new_sites = collections.defaultdict(list)
    needs_gdb = collections.defaultdict(list)
    other = collections.Counter()

    jobs = _resolve_jobs(len(dirs))
    if jobs == 1:
        _worker_init(snap, cache)  # set worker globals for the in-process path
        results = [classify_dir(d) for d in dirs]
    else:
        # CPU-bound + independent -> fan out over processes. fork (not spawn/forkserver) so
        # workers don't re-run this module's top-level argv parsing; the snapshot/cache go in
        # via the initializer. map() preserves input order, so the reduce below -- and the
        # whole report -- is byte-identical to the --jobs 1 path.
        ctx = mp.get_context("fork")
        with cf.ProcessPoolExecutor(
            max_workers=jobs, mp_context=ctx,
            initializer=_worker_init, initargs=(snap, cache),
        ) as pool:
            results = list(pool.map(classify_dir, dirs, chunksize=64))

    # ---- reduce (single-threaded; identical regardless of --jobs) ----
    for category, key, label in results:
        if category == "skip":
            continue
        elif category == "other":
            other[key] += 1
        elif category == "known":
            known[key].append(label)
        elif category == "ambiguous":
            ambiguous[key].append(label)
        elif category == "needs_gdb":
            needs_gdb[key].append(label)
        else:  # "new"
            new_sites[key].append(label)

    # ---- report ----
    print(f"# ingested {len(dirs)} run-dirs | snapshot={SNAP.name} cache={'yes' if cache else 'no'} "
          f"gdb={USE_GDB} jobs={jobs}\n")
    print("## NEW crash sites (need a report) " + "-" * 30)
    if not new_sites:
        print("  (none -- every resolved crash matched the catalog)")
    for (kind, key), labels in sorted(new_sites.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{len(labels):>3}] {kind:6} {key}\n        e.g. {', '.join(labels[:3])}")
    if needs_gdb:
        print("\n## SEGV needing resolution (--gdb or --sites-cache) " + "-" * 12)
        for chain, labels in sorted(needs_gdb.items(), key=lambda kv: -len(kv[1])):
            print(f"  [{len(labels):>3}] {chain}   e.g. {labels[0]}")
    print("\n## known-bug vehicles (dedupe tally) " + "-" * 27)
    for oid, labels in sorted(known.items(), key=lambda kv: -len(kv[1])):
        extra = f"   prune {len(labels)-KEEP} (keep {KEEP})" if KEEP and len(labels) > KEEP else ""
        print(f"  {oid} [{snap['kind'].get(oid,'?'):5}]: {len(labels)} vehicles{extra}")
    if ambiguous:
        print("\n## ambiguous (matched >1 bug -- still known, not new) " + "-" * 10)
        for ids, labels in sorted(ambiguous.items(), key=lambda kv: -len(kv[1])):
            print(f"  {ids}: {len(labels)}")
    print(f"\n## other: {dict(other)}  |  needs-gdb: {sum(len(v) for v in needs_gdb.values())}  |  "
          f"new-site groups: {len(new_sites)}")

    if JSON_OUT:
        out = {"new_sites": {f"{k[0]}|{k[1]}": v for k, v in new_sites.items()},
               "known": {k: len(v) for k, v in known.items()},
               "needs_gdb": {k: v for k, v in needs_gdb.items()}}
        pathlib.Path(JSON_OUT).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {JSON_OUT}")


if __name__ == "__main__":
    main()
