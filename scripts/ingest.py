#!/usr/bin/env python3
"""Ingest a pile of fuzzer run-dirs, dedupe them against the read-only catalog snapshot
(catalog/known_sites.tsv), and surface ONLY genuinely-new crash sites. This is the
single-writer merge step: instances (or a batch) feed their crash dirs in; known-bug
vehicles are tallied and prunable, new sites are flagged for a report. No shared mutable
state -- it only READS the snapshot.

Tiered resolution (cheap -> expensive):
  1. stdout (no execution): aborts carry an exact `file:line: func(): Assertion ...`;
     fatals carry a `Fatal Python error: <msg>`. Both dedupe build-stably.
  2. segvs have no reliable C site in stdout -> resolve via --sites-cache <tsv>
     (precomputed by segv_sweep.sh, or by an in-loop hook) or --gdb (segv_worker.sh).
     Without either, segvs are grouped coarsely and flagged needs-gdb.

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
ASSERT = re.compile(r"([\w./+-]+\.(?:c|h)):(\d+):[^\n]*?\b(\w+)\s*\([^)]*\)\s*:\s*Assertion `([^']*)' failed")
ASSERT2 = re.compile(r"([\w./+-]+\.(?:c|h)):(\d+):[^\n]*?Assertion `([^']*)' failed")
FATAL = re.compile(r'Fatal Python error:\s*([^\n]+)')
SEGV = re.compile(r'AddressSanitizer: SEGV|Fatal Python error: Segmentation fault|Segmentation fault')
IMPORTERR = re.compile(r'(ModuleNotFoundError|ImportError):')
SYM = re.compile(r', at ([A-Za-z_]\w+)\+0x')
SKIP = re.compile(r'^(___?interceptor\w*|__sanitizer\w*|__asan\w*|_Py_DumpStack|faulthandler\w*|_PyEval_EvalFrameDefault|_PyEval_Vector|PyEval_EvalCode|Py_RunMain|Py_BytesMain|pymain_\w+|_start|__libc_start\w*)$')
FRAME = re.compile(r'([A-Za-z_]\w+)@([\w./+-]+\.(?:c|h)):(\d+)')


def nf(f):
    return f.lstrip("./")


def classify(text):
    """-> dict(kind, file, line, func, assert_expr, fatal_msg, chain) or kind=clean/import."""
    m = ASSERT.search(text) or ASSERT2.search(text)
    if m:
        g = m.groups()
        if len(g) == 4:
            f, ln, func, expr = g
        else:
            f, ln, expr = g; func = None
        return dict(kind="abort", file=nf(f), line=int(ln), func=func, assert_expr=expr.strip(),
                    fatal_msg=None, chain=None)
    fa = FATAL.search(text)
    if fa and not SEGV.search(text):
        msg = fa.group(1).strip()
        # generic assert wrappers carry no site in stdout -> resolve via gdb/cache,
        # don't trust the non-discriminative message.
        if msg.startswith(("_PyObject_AssertFailed", "_Py_NegativeRefcount")):
            return dict(kind="segv", file=None, line=None, func=None, assert_expr=None,
                        fatal_msg=None, chain=msg[:50])
        return dict(kind="fatal", file=None, line=None, func=None, assert_expr=None,
                    fatal_msg=msg[:60], chain=None)
    if SEGV.search(text):
        chain = [s for s in SYM.findall(text) if not SKIP.match(s)][:3]
        return dict(kind="segv", file=None, line=None, func=None, assert_expr=None,
                    fatal_msg=None, chain=" <- ".join(chain) or "(no-sym)")
    if IMPORTERR.search(text):
        return dict(kind="import", chain=None)
    return dict(kind="clean", chain=None)


# ---- snapshot matcher ----
def load_snapshot(path):
    by_func, by_assert = {}, {}
    by_line = {}
    per_file_lines = collections.defaultdict(list)
    by_msg = []
    kind_of = {}
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
    """Return (set(oom_ids), how) or (empty, 'NEW')."""
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
                return {oid}, f"near({c['line']-ln:+d})"
    return set(), "NEW"


# ---- sites cache (precomputed local segv sites) ----
def load_cache(path):
    cache = {}
    if path and os.path.exists(path):
        for line in open(path):
            f = line.rstrip("\n").split("\t")
            if len(f) >= 3:
                cache[f[0]] = (f[1], f[2])   # label -> (signal, site)
    return cache


def resolve_segv(crash_dir, label, cache):
    """Fill file/func/line for a segv via cache or gdb; returns updated classify dict."""
    site = None
    if label in cache:
        site = cache[label][1]
    elif USE_GDB:
        try:
            out = subprocess.run(["bash", str(HERE / "segv_worker.sh"), crash_dir],
                                 capture_output=True, text=True, timeout=240).stdout
            parts = out.strip().split("\t")
            if len(parts) >= 3:
                site = parts[2]
        except Exception:
            site = None
    if site:
        m = FRAME.match(site)
        if m:
            return dict(file=nf(m.group(2)), func=m.group(1), line=int(m.group(3)))
    return None


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

    known = collections.defaultdict(list)     # oom_id -> [labels]
    ambiguous = collections.defaultdict(list)
    new_sites = collections.defaultdict(list)  # (kind, key) -> [labels]
    needs_gdb = collections.defaultdict(list)  # coarse chain -> [labels]
    other = collections.Counter()

    for d in dirs:
        label = f"{os.path.basename(os.path.dirname(d))}/{os.path.basename(d)}"
        try:
            text = open(os.path.join(d, "stdout"), errors="replace").read()
        except OSError:
            continue
        c = classify(text)
        if c["kind"] in ("clean", "import"):
            other[c["kind"]] += 1
            continue
        if c["kind"] == "segv":
            r = resolve_segv(d, label, cache)
            if r:
                c.update(r)
            else:
                needs_gdb[c["chain"]].append(label)
                continue
        hit, how = match(c, snap)
        if not hit:
            key = (c["assert_expr"] and f"{c['file']}:{c['assert_expr']}") or \
                  (c.get("func") and f"{c['file']}:{c['func']}") or \
                  c.get("fatal_msg") or c.get("chain") or "?"
            new_sites[(c["kind"], key)].append(label)
        elif len(hit) == 1:
            known[next(iter(hit))].append(label)
        else:
            ambiguous["|".join(sorted(hit))].append(label)

    # ---- report ----
    nd = len(dirs)
    print(f"# ingested {nd} run-dirs | snapshot={SNAP.name} cache={'yes' if cache else 'no'} gdb={USE_GDB}\n")
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
