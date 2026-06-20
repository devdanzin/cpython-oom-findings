"""OOM-0036, natural trigger: the same double-free WITHOUT _testcapi.

`_CALL_LIST_APPEND`'s only error path is `list_resize` failing, which happens only on a
genuine allocation failure. So the bug fires under real memory pressure -- `set_nomemory`
just makes it deterministic. Here a real `RLIMIT_AS` address-space cap makes the list's grow
allocation return NULL, and `list.append(x)` of a still-referenced object segfaults on a
stock release interpreter.

Run on a NON-ASan build (ASan reserves a huge virtual address space, which defeats
RLIMIT_AS):  PYTHON_GIL=1 ./python repro_natural.py   ->  Segmentation fault (3/3).

Contrast: under the same cap, when the failing allocation is NOT a list-append grow (e.g.
appending large `bytes`), Python raises a clean, catchable MemoryError and does NOT crash.
"""
import resource

# Pre-build a pool of uniquely-referenced objects BEFORE capping memory, so that inside the
# capped loop the ONLY allocation is the list's own resize -- the failure lands exactly there.
pool = [object() for _ in range(8_000_000)]

# Warm up so `out.append(x)` specializes to CALL_LIST_APPEND (the buggy uop).
warm = []
for i in range(3000):
    warm.append(pool[i])
del warm

# Cap the address space to just above current usage: the next big list grow will fail.
cur = int(open("/proc/self/statm").read().split()[0]) * 4096   # current virtual size (bytes)
cap = cur + 24 * 1024 * 1024                                    # +24 MB headroom
resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

out = []
for x in pool:
    out.append(x)        # real list_resize failure -> double-free of x (still held by pool) -> SIGSEGV
