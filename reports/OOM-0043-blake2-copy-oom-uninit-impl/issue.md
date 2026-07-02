**Title:** `hashlib` BLAKE2 `.copy()` crashes with `Py_UNREACHABLE` in `py_blake2_clear` when the copy's allocation fails

**Body:**

`_blake2.blake2b`/`_blake2.blake2s` carry an `impl` enum that `py_blake2_clear` (the `tp_clear`/dealloc path) switches on, with a `Py_UNREACHABLE()` default. The `.copy()` method allocates a new object whose `impl` is left uninitialized, then performs the (fallible) HACL\* state allocation; if that allocation fails, the error path deallocates the half-built object without ever setting `impl`, so `py_blake2_clear` reads garbage and hits `Py_UNREACHABLE()`:

```
Fatal Python error: py_blake2_clear: We've reached an unreachable state. ...
```

On a debug build this is a deterministic fatal error; on a release build `Py_UNREACHABLE()` is `__builtin_unreachable()`, so a garbage `impl` is undefined behaviour (I observed a SIGSEGV on a free-threaded release build; and if the garbage value happens to match a valid enum case, `py_blake2_clear` calls `Hacl_Hash_*_free()` on an uninitialized state pointer — a wild free).

## Reproducer

The failing allocation is HACL\*'s raw `malloc()` for the copy's hash state, which `_testcapi.set_nomemory` (a PyMem hook) cannot reach — so the failure is injected at the C `malloc` layer with a tiny `LD_PRELOAD` shim. **Needs a non-ASan build** (ASan owns `malloc`, bypassing the shim).

```c
/* oomshim.c:  cc -shared -fPIC -O2 -o oomshim.so oomshim.c -ldl
 * arm_next_malloc() makes the very next malloc() return NULL. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <string.h>
static void *(*real_malloc)(size_t); static void *(*real_calloc)(size_t,size_t);
static void (*real_free)(void*); static int armed = 0;
static char boot[16384]; static size_t boot_off = 0; static int initing = 0;
static int is_boot(const void*p){return (const char*)p>=boot&&(const char*)p<boot+sizeof boot;}
static void init_reals(void){ initing=1; real_malloc=dlsym(RTLD_NEXT,"malloc");
    real_calloc=dlsym(RTLD_NEXT,"calloc"); real_free=dlsym(RTLD_NEXT,"free"); initing=0; }
void arm_next_malloc(void){ armed = 1; }
void *malloc(size_t n){ if(!real_malloc){ if(initing){void*p=boot+boot_off;boot_off+=(n+15)&~(size_t)15;return p;} init_reals(); }
    if(armed){ armed=0; errno=ENOMEM; return NULL; } return real_malloc(n); }
void *calloc(size_t a,size_t b){ if(!real_calloc){ if(initing){void*p=boot+boot_off;boot_off+=((a*b)+15)&~(size_t)15;memset(p,0,a*b);return p;} init_reals(); }
    return real_calloc(a,b); }
void free(void*p){ if(is_boot(p))return; if(!real_free)init_reals(); if(real_free)real_free(p); }
```

```python
# repro.py  —  LD_PRELOAD=./oomshim.so ./python repro.py
import ctypes, faulthandler
faulthandler.enable()
import _blake2

lib = ctypes.CDLL(None)
h = _blake2.blake2s(b"data")   # (blake2b behaves identically)
lib.arm_next_malloc()          # next malloc() returns NULL
h.copy()                       # -> Fatal Python error: py_blake2_clear ...
```

## Traceback (debug build, gdb)

```
#8  py_blake2_clear            Modules/blake2module.c:997   # default: Py_UNREACHABLE() — reads uninitialized self->impl
#9  py_blake2_dealloc          Modules/blake2module.c:1008
#10 _Py_Dealloc               Objects/object.c:3319
#11 Py_DECREF                 Include/refcount.h:359
#12 _blake2_blake2b_copy_impl Modules/blake2module.c:812    # Py_DECREF(cpy) after the copy failed
```

## Root cause

`new_Blake2Object` (`blake2module.c:387`) uses `PyObject_GC_New` (memory not zeroed) and immediately `PyObject_GC_Track`s the object, leaving `impl` and the state pointers uninitialized; each caller is responsible for initializing them. `py_blake2_new` does so immediately, before any fallible allocation. But `blake2_blake2b_copy_unlocked` (`blake2module.c:749`) does the fallible HACL allocation first and only sets `cpy->impl = self->impl` on success (line 781); its `error:` path returns `-1` with `impl` still uninitialized, and `_blake2_blake2b_copy_impl` then `Py_DECREF`s that object (line 812) → `py_blake2_clear` reads the garbage discriminant.

## Suggested fix

Initialize the discriminant (and NULL the state pointer) before the fallible allocation, mirroring `py_blake2_new` — e.g. at the top of `blake2_blake2b_copy_unlocked`:

```c
cpy->impl = self->impl;
/* leave the state pointer NULL until the copy succeeds, so py_blake2_clear is a no-op on error */
```

(Alternatively, have `new_Blake2Object` zero-initialize the struct so no caller can leave `impl` uninitialized.)

## Environment

- CPython `main` (3.16.0a0), commit `1b9fe5c`; reproduced on debug free-threaded and GIL builds (deterministic fatal) and a release free-threaded build (SIGSEGV). Linux x86-64.
- The copy path's structure dates to the 2024 HACL BLAKE2 rewrite (`325e9b8`); most recently reworked in gh-135532 (#135838).

Found via allocation-failure fuzzing with [fusil](https://github.com/devdanzin/fusil), created by @vstinner.

*The investigation was conducted and this report was drafted with the help of Claude Code (Opus 4.8).*
