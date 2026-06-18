#!/usr/bin/env python3
"""Cheap dedupe: cluster crash dirs by a signature parsed from their saved stdout
(no gdb, no agents). abort/fatal cluster robustly by assertion file:line / fatal
message; segv is coarse (first named CPython C-stack symbol, else top Lib frame) and
should be refined with gdb. Flags clusters already covered by reports/*/meta.json.

Usage: cluster_stdout.py [<glob-of-stdout> ...]   (default: ~/crashers/*/*/stdout etc.)
"""
import sys, re, glob, os, json, collections, pathlib

GLOBS = sys.argv[1:] or [os.path.expanduser("~/crashers/python-*/*/stdout"),
                         os.path.expanduser("~/crashers/*/stdout")]
ROOT = pathlib.Path(__file__).resolve().parent.parent

ASSERT = re.compile(r'([\w./+-]+\.(?:c|h)):(\d+):[^\n]*?Assertion', re.I)
STACKREF = re.compile(r'(pycore_\w+\.h):(\d+)')
FATAL = re.compile(r'Fatal Python error:\s*(.+)')
SEGV = re.compile(r'AddressSanitizer: SEGV|Segmentation fault')
PYFRAME = re.compile(r'File "[^"]*/Lib/([^"]+)", line \d+ in (\w+)')
CSYM = re.compile(r', at ([A-Za-z_]\w+)\+0x')
IMPORT = re.compile(r'(ModuleNotFoundError|ImportError):')
C_GENERIC = re.compile(r'^(_PyEval_\w+|PyEval_\w+|_Py_VectorCall\w+|_PyObject_\w*[Cc]all\w*|'
                       r'Py_RunMain|Py_BytesMain|_start|cfunction_\w+|_Py_DumpStack|'
                       r'___interceptor\w+|pymain_\w+|run_\w+|_PyRun_\w+|method_vectorcall\w*)$')


def sig(text):
    m = ASSERT.search(text)
    if m:
        return ("abort", f"{m.group(1).lstrip('./')}:{m.group(2)}")
    if '_Py_NegativeRefcount' in text or 'Assertion failed:' in text:
        s = STACKREF.search(text)
        if s:
            return ("abort", f"{s.group(1)}:{s.group(2)}")
    f = FATAL.search(text)
    if f and not SEGV.search(text) and 'AssertFailed' not in f.group(1):
        return ("fatal", f.group(1).strip()[:70])
    if SEGV.search(text):
        for s in CSYM.findall(text):
            if not C_GENERIC.match(s):
                return ("segv", f"C:{s}")
        p = PYFRAME.search(text)
        return ("segv", f"py:{p.group(1)}:{p.group(2)}") if p else ("segv", "?")
    if IMPORT.search(text):
        return ("import", "ModuleNotFoundError")
    return ("unknown", "?")


def known_sites():
    sites = {}
    for meta in ROOT.glob("reports/*/meta.json"):
        d = json.loads(meta.read_text())
        for s in d.get("sites", []):
            m = re.search(r'([\w./]+\.(?:c|h)):(\d+)', s)
            if m:
                sites[f"{m.group(1).lstrip('./')}:{m.group(2)}"] = d["id"]
    return sites


clusters = collections.defaultdict(list)
for g in GLOBS:
    for sp in glob.glob(g):
        d = os.path.basename(os.path.dirname(sp))
        run = os.path.basename(os.path.dirname(os.path.dirname(sp)))
        try:
            clusters[sig(open(sp, errors="replace").read())].append(f"{run}/{d}")
        except OSError:
            pass

known = known_sites()
total = sum(len(v) for v in clusters.values())
by_kind = collections.Counter(k for (k, _), v in clusters.items() for _ in v)
print(f"# {total} dirs -> {len(clusters)} clusters | by kind: {dict(by_kind)}\n")
print(f"{'cnt':>4} {'kind':7} {'known':9} signature")
for (kind, s), veh in sorted(clusters.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
    flag = known.get(s.split(":C:")[-1] if s.startswith("C:") else s, "")
    print(f"{len(veh):>4} {kind:7} {flag or 'NEW':9} {s}   e.g. {veh[0]}")
