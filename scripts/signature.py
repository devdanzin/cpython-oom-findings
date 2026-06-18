#!/usr/bin/env python3
"""Normalize a gdb backtrace into a dedupe signature.

The faulting frames of these OOM crashes are almost always generic refcount/abort
plumbing (`Py_DECREF`, `_Py_atomic_*`, `_PyObject_AssertFailed`, eval loop, libc).
Those are skipped; the signature keys on the first *project-specific* frame (the
crash SITE) plus the next few callers.

Usage:
    signature.py <backtrace.txt>          # print JSON signature
    (importable: signature(path) -> dict)
"""
import sys, re, json, hashlib

# Frames that are not bug-identifying (shared across unrelated OOM crashes).
GENERIC = re.compile(r"""^(
    _Py_atomic_\w+ | Py_X?DECREF | Py_X?INCREF | Py_X?NewRef | _Py_Dealloc |
    _Py_NegativeRefcount | _PyObject_AssertFailed | _Py_FatalErrorFunc |
    fatal_error\w* | abort | __GI_abort | __GI_raise | raise | gsignal |
    __pthread_kill\w* | pthread_kill | __interceptor_\w+ | _Py_DumpStack |
    _PyEval_EvalFrame\w* | _PyEval_Vector | PyEval_EvalCode | run_eval_code_obj |
    run_mod | pyrun_\w+ | _PyRun_\w+ | pymain_\w+ | Py_RunMain | Py_BytesMain |
    _start | __libc_start\w* | _PyObject_(Vectorcall|MakeTpCall|Call)\w* |
    cfunction_vectorcall\w* | _PyObject_VectorcallTstate | method_vectorcall\w*
)$""", re.X)

FRAME = re.compile(
    r"^#\d+\s+(?:0x[0-9a-f]+ in\s+)?(?P<func>[A-Za-z_][\w.]*)\s*\(.*?\)"
    r"(?:\s+at\s+(?P<loc>\S+))?"
)


def signature(path):
    kind = "segv"
    frames = []
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("#"):
                pass  # frame line
            if "SIGABRT" in line:
                kind = "abort"
            elif "Fatal Python error" in line:
                kind = "fatal"
            m = FRAME.match(line)
            if m:
                loc = m.group("loc") or ""
                frames.append(f"{m.group('func')}@{loc}" if loc else m.group("func"))
    nongeneric = [f for f in frames if not GENERIC.match(f.split("@")[0])]
    site = nongeneric[0] if nongeneric else (frames[0] if frames else "?")
    top = nongeneric[:4]
    h = hashlib.sha1("|".join(top).encode()).hexdigest()[:12]
    return {"kind": kind, "site_frame": site, "top_frames": top, "hash": h}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: signature.py <backtrace.txt>")
    print(json.dumps(signature(sys.argv[1]), indent=2))
