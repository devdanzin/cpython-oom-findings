#!/usr/bin/env python3
"""Refine segv crash dirs into tight sub-clusters using the faulthandler C-stack in
each dir's stdout (no gdb). The precise crash site is usually a *static* function
shown only as a raw `+0xNNNN` offset (relative to the fuzz host's binary, which we
don't have locally), so the grouping key is the chain of named *exported* symbols
around the crash. Dirs sharing a key are candidate vehicles of one bug; gdb a
representative under the local debug build to resolve the real static site + dedupe.

Usage: cluster_segv.py [<glob-of-stdout> ...]   (default: ~/crashers/python-*/*/stdout)
"""
import sys, re, glob, os, collections, pathlib

GLOBS = sys.argv[1:] or [os.path.expanduser("~/crashers/python-*/*/stdout")]

SEGV = re.compile(r'AddressSanitizer: SEGV|Fatal Python error: Segmentation fault|Segmentation fault')
# A named-symbol frame: `at <symbol>+0x...`. Offset-only frames (`at +0x...`) have no symbol.
SYM = re.compile(r', at ([A-Za-z_]\w+)\+0x')
PYFRAME = re.compile(r'File "([^"]+)", line \d+ in (\S+)')

# Frames that carry no bug-identity: the faulthandler/asan dumper prologue and the
# ubiquitous eval/call-dispatch/runmain/libc tail. Everything else (incl. specific
# call helpers like PyObject_CallOneArg, _Py_Dealloc, PyList_New) stays in the key.
SKIP = re.compile(r'^(___?interceptor\w*|__sanitizer\w*|__asan\w*|_Py_DumpStack|'
                  r'faulthandler\w*|_PyEval_EvalFrameDefault|_PyEval_EvalFrame\b|'
                  r'_PyEval_Vector|PyEval_EvalCode|Py_RunMain|Py_BytesMain|'
                  r'pymain_\w+|_start|__libc_start\w*|_PyEval_Run\w*|_PyRun\w*)$')

KEYLEN = 3


def parse(text):
    """Return (key_tuple, full_named_chain, innermost_py)."""
    chain = []
    for sym in SYM.findall(text):
        if not SKIP.match(sym):
            chain.append(sym)
    key = tuple(chain[:KEYLEN])
    pys = PYFRAME.findall(text)
    inner = f"{pys[0][0].split('/')[-1]}:{pys[0][1]}" if pys else "?"
    return key, tuple(chain[:6]), inner


clusters = collections.defaultdict(list)
chains = {}
for g in GLOBS:
    for sp in glob.glob(g):
        try:
            text = open(sp, errors="replace").read()
        except OSError:
            continue
        if not SEGV.search(text):
            continue
        d = os.path.basename(os.path.dirname(sp))
        run = os.path.basename(os.path.dirname(os.path.dirname(sp)))
        key, full, inner = parse(text)
        clusters[key].append((f"{run}/{d}", inner))
        chains[key] = full

total = sum(len(v) for v in clusters.values())
print(f"# {total} segv dirs -> {len(clusters)} sub-clusters (key = top {KEYLEN} named exported symbols)\n")
for key, veh in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
    keys = " <- ".join(key) if key else "(no named frames)"
    inners = sorted({i for _, i in veh})
    print(f"## [{len(veh):>3}]  {keys}")
    print(f"        chain: {' <- '.join(chains[key])}")
    print(f"        py-callees ({len(inners)}): {', '.join(inners[:8])}{' ...' if len(inners) > 8 else ''}")
    print(f"        e.g. {veh[0][0]}")
    print()
