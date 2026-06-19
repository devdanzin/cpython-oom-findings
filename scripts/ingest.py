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
  ingest.py [globs...] [--snapshot F] [--sites-cache F] [--gdb] [--keep N] [--json F]
  default globs: ~/crashers/python-*/*  and ~/crashers/*/   (dirs containing stdout)
"""
import sys, os, re, json, glob, subprocess, collections, pathlib

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
ASAN_FRAME = re.compile(r'#\d+\s+0x[0-9a-fA-F]+\s+in\s+(\w+)\s+\S*?'
                        r'/((?:Objects|Python|Modules|Include|Parser)/[\w./+-]+\.(?:c|h)):(\d+)')
NATIVE_SKIP = re.compile(r'^(fatal_error(_exit)?|_Py_FatalError\w*|_PyObject_AssertFailed'
                         r'|_Py_NegativeRefcount|_Py_DumpStack|faulthandler\w*'
                         r'|_Py_DumpExtensionModules)$')
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
    by_msg, kind_of = [], {}
    for line in pathlib.Path(path).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        oid, kind, kt, key = line.split("\t")
        kind_of[oid] = kind
        if kt == "func":
            by_func.setdefault(key, set()).add(oid)
        elif kt == "assert":
            by_assert.setdefault(key, set()).add(oid)
        elif kt == "msg":
            by_msg.append((key, oid))
        elif kt == "line":
            f, ln = key.rsplit(":", 1); ln = int(ln)
            by_line.setdefault((f, ln), set()).add(oid)
            per_file_lines[f].append((ln, oid))
    return dict(func=by_func, assert_=by_assert, line=by_line,
                fl=per_file_lines, msg=by_msg, kind=kind_of)


def match(c, snap):
    """Match ONE candidate dict -> (set(oom_ids), how) or (empty, 'NEW')."""
    if c.get("assert_expr") and c.get("file"):
        hit = snap["assert_"].get(f"{c['file']}:{c['assert_expr']}")
        if hit:
            return hit, "assert"
    if c.get("fatal_msg"):
        hit = set(o for k, o in snap["msg"] if c["fatal_msg"].startswith(k) or k.startswith(c["fatal_msg"][:30]))
        if hit:
            return hit, "msg"
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


# ---- main ----
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

    for d in dirs:
        label = f"{os.path.basename(os.path.dirname(d))}/{os.path.basename(d)}"
        try:
            text = open(os.path.join(d, "stdout"), errors="replace").read()
        except OSError:
            continue
        asserts = all_asserts(text)
        fa = FATAL.search(text)
        fmsg = fa.group(1).strip() if fa else None
        has_segv = bool(SEGV.search(text))
        generic = bool(fmsg) and fmsg.startswith(GENERIC_FATAL)

        if not asserts and not has_segv and not fmsg:
            other["import" if IMPORTERR.search(text) else "clean"] += 1
            continue

        candidates = [dict(file=f, line=ln, func=fn, assert_expr=expr, fatal_msg=None)
                      for (f, ln, fn, expr) in asserts]
        if fmsg and not generic and not fmsg.lower().startswith(("segmentation", "aborted")):
            candidates.append(dict(file=None, line=None, func=None, assert_expr=None, fatal_msg=fmsg[:60]))

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

        if matched:
            (known if len(matched) == 1 else ambiguous)[
                next(iter(matched)) if len(matched) == 1 else "|".join(sorted(matched))].append(label)
        elif (has_segv or generic) and not chain:
            coarse = (" <- ".join([s for s in SYM.findall(text) if not SKIP.match(s)][:3])
                      or (fmsg[:50] if fmsg else "(no-sym)"))
            needs_gdb[coarse].append(label)
        else:
            prim = candidates[0] if candidates else {}
            key = (prim.get("assert_expr") and f"{prim['file']}:{prim['assert_expr']}") or \
                  (prim.get("func") and f"{prim['file']}:{prim['func']}") or \
                  prim.get("fatal_msg") or (chain[0] if chain else "?")
            kind = "abort" if asserts else ("segv" if has_segv else "fatal")
            new_sites[(kind, key)].append(label)

    # ---- report ----
    print(f"# ingested {len(dirs)} run-dirs | snapshot={SNAP.name} cache={'yes' if cache else 'no'} gdb={USE_GDB}\n")
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
