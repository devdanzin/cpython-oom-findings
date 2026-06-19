"""OOM-0035 minimal reproducer (stdlib only).

Repeatedly writing to an io.StringIO under intermittent allocation failure grows its
internal Py_UCS4 buffer (resize_buffer / PyMem_Realloc); a grow-under-OOM leaves
UNINITIALIZED Py_UCS4 garbage inside the buffer's [0, string_size) range. getvalue()
then builds the result str from that buffer:

  _io_StringIO_getvalue_impl (Modules/_io/stringio.c:294)
    -> _PyUnicode_FromUCS4(buf, string_size) (Objects/unicodeobject.c:2228)
       -> ucs4lib_find_max_char scans the garbage -> a value > 0x10ffff
       -> PyUnicode_New(size, bad_maxchar) -> a str with an invalid maxchar field
  -> assert _PyUnicode_CheckConsistency: `maxchar <= MAX_UNICODE` (unicodeobject.c:673)

Debug builds abort here; release builds get a silently-malformed str (jit segvs).

Two phases mirror the fuzzer's per-method OOM sweeps: phase 1 accumulates (writes swept
~1000x, growing the buffer to ~33k chars), phase 2 reads it back via getvalue.
"""
import faulthandler, io
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

s = io.StringIO()
chunk = "stringio-oom-chunk" * 2          # any small ASCII text, repeated to grow the buffer
for start in range(0, 1000):              # phase 1: accumulate under intermittent OOM
    try:
        set_nomemory(start, 0)
        try:
            s.writelines(chunk)
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
for start in range(0, 1000):              # phase 2: read it back -> consistency check
    try:
        set_nomemory(start, 0)
        try:
            s.getvalue()
        finally:
            remove_mem_hooks()
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
print("done, no crash")
