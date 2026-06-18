"""
Minimal reproducer: abort on assert(release1 == (buf1 != PyUnicode_DATA(str1)))
in replace() (str.replace) when a kind-widening allocation fails under OOM.

Affected:   CPython 3.16.0a0 (main). Reproduces as an abort on builds with
            assertions enabled (free-threaded debug+ASan, JIT debug). Release
            builds define NDEBUG, so the assert is a no-op and str.replace
            correctly raises MemoryError instead (see Notes).
Crash:      SIGABRT, Objects/unicodeobject.c:10783
            Assertion `release1 == (buf1 != PyUnicode_DATA(str1))' failed.
Requires:   a build exposing _testcapi.set_nomemory.

Run:
    python repro.py            # aborts (rc 134) on FT debug+ASan / JIT debug

Backtrace (gdb):
    #8  replace               Objects/unicodeobject.c:10783 (assert release1 ...)
    #9  unicode_replace_impl   Objects/unicodeobject.c:12586 (str.replace)
    #10 unicode_replace        Objects/clinic/unicodeobject.c.h:1002
    #11 _PyCallMethodDescriptorFastWithKeywords_StackRef Python/ceval.c:883

Root cause (Objects/unicodeobject.c):

    replace() (L10515) tracks three "owned scratch buffer" flags --
    srelease/release1/release2 -- which must stay consistent with their
    pointers (sbuf/buf1/buf2). When a substring/replacement of a narrower
    PyUnicode kind must be widened, the code does e.g. (L10644):

        if (kind1 < rkind) {
            buf1 = unicode_askind(kind1, buf1, len1, rkind);  // PyMem_New
            if (!buf1) goto error;     // buf1 is now NULL, release1 STILL 0
            release1 = 1;
        }

    unicode_askind() allocates with PyMem_New and returns NULL under OOM.
    On that failure buf1 becomes NULL while release1 is still 0, then
    'goto error' jumps to the cleanup labels (error/nothing/done) which all
    assert:

        assert(release1 == (buf1 != PyUnicode_DATA(str1)));   // L10783

    Now release1 == 0 but (buf1==NULL) != PyUnicode_DATA(str1) is true (1),
    so the assertion fails and the interpreter aborts. The same desync
    hazard exists for srelease/sbuf and release2/buf2 (L10583/10592/10605/
    10608/10646/10655/10662/10671).

Trigger here: html.escape's first step is "s.replace('&', '&amp;')".
For a non-Latin-1 (UCS-2) input string, the ASCII substring "&" (1-byte
kind) must be widened to 2-byte kind via unicode_askind. Failing that very
first allocation (start=0) hits the desync.

Observed crash at start=0 on the FT debug+ASan and JIT debug builds.
"""
import sys
import _testcapi
import faulthandler

faulthandler.enable()

# A UCS-2 (2-byte kind) string: forces the ASCII "&" substring to be widened
# inside replace() via unicode_askind() (a PyMem_New allocation).
s = "轘" * 4

_testcapi.set_nomemory(0, 0)   # fail every allocation from #0 onward
try:
    s.replace("&", "&amp;")    # unicode_askind(str1) fails -> buf1=NULL, release1=0
                               # -> goto error -> assert release1 == ... -> SIGABRT
finally:
    _testcapi.remove_mem_hooks()
