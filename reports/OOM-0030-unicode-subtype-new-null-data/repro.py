"""OOM-0030 minimal reproducer (stdlib only) — reduced from the fuzzer vehicle with shrinkray.

Parsing an email header value containing a NUL byte under allocation failure instantiates a
`str` subclass whose data buffer was not allocated; freeing it trips the unicode consistency
check:

  email._header_value_parser.get_value("\\x00")  under the set_nomemory sweep
    -> a str-subclass token is created with NULL data, then deallocated
    -> unicode_dealloc -> unicode_is_singleton -> _PyUnicode_NONCOMPACT_DATA asserts
       `data != NULL` (Objects/unicodeobject.c) -> SIGABRT (debug) / NULL deref (release).

Same "partially-constructed object freed on the OOM error path" class as OOM-0024/0035;
here via str-subclass instantiation (unicode_subtype_new). Deterministic (re-verified 40x).
"""
import faulthandler
import email._header_value_parser as hvp
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks

for start in range(0, 40):
    try:
        set_nomemory(start, 0)
        try:
            hvp.get_value("\x00")
        finally:
            remove_mem_hooks()
    except MemoryError:
        pass
    except BaseException:
        pass
    finally:
        try:
            remove_mem_hooks()
        except Exception:
            pass
print("done, no crash")
