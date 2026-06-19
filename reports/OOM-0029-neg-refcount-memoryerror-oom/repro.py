"""OOM-0029 minimal reproducer (stdlib only) — reduced from the _pyrepl.utils fuzz vehicle with shrinkray.

Under a dense allocation-failure sweep, `_pyrepl.utils.disp_str(<mixed control/high string>)`
over-decrefs a `MemoryError` on an OOM error path. The corruption is silent until that
already-negative-refcount `MemoryError` is `Py_DECREF`'d again during an unrelated dealloc
cascade (`list_dealloc -> subtype_dealloc -> tuple_dealloc`), where `_Py_NegativeRefcount`
(Objects/object.c:275, reported at the caller `tuple_dealloc` Objects/tupleobject.c:277) fires
and aborts. Debug-only detector (Py_DEBUG); on release the negative refcount is a silent UAF.

Deterministic: aborts on every run (30/30, GIL=1). Requires a debug build. The crash-time
backtrace is symbolized with `ASAN_OPTIONS=...:handle_abort=1` (no gdb needed); the
`tuple_dealloc -> subtype_dealloc -> list_dealloc` cascade is identical on every run.

The argument is load-bearing: it mixes NUL/control bytes and high bytes
(`\x00`, `4`, `\x8a`, `\xd5`, `\x03`), exercising disp_str's control-char / wide-char display
path; a single character (`"\x00"`, `"\x8a"`) does not reproduce. The over-decref site itself
is not pinned to a single line (root cause PARTIAL); the full vehicle is preserved as
`vehicle_source.py`.
"""
import _pyrepl.utils
from _testcapi import set_nomemory

for start in range(150):
    set_nomemory(start, 0)
    try:
        _pyrepl.utils.disp_str("\x004\x8A\xD5\x03")
    except MemoryError:
        pass
