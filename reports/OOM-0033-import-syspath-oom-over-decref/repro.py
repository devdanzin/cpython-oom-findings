import sys, faulthandler
faulthandler.enable()
from _testcapi import set_nomemory, remove_mem_hooks
saved = list(sys.path)
S = "轆ﰲ匀漏㗢攥㥔䘧ꝺᲮ緧"
for start in range(0, 1000):
    try:
        set_nomemory(start, 0)
        try:
            sys.path[:] = S        # like _handle_preload's sys.path[:] = sys_path
            __import__("H")        # iterate the (corrupted) sys.path in _get_spec
        finally:
            remove_mem_hooks()
    except (MemoryError, ImportError):
        pass
    except BaseException:
        pass
    finally:
        try: remove_mem_hooks()
        except Exception: pass
        try: sys.path[:] = saved
        except Exception: pass
print("done, no crash")
