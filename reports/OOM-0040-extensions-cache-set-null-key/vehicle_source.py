# FUSIL_BOILERPLATE_START

from gc import collect
from random import choice, randint, random, sample, seed
from sys import stderr, path as sys_path
from os.path import dirname
import ast
import inspect
import io
import math
import operator
import time
import sys
from threading import Thread
from unittest.mock import MagicMock
import asyncio
seed(499933619)

from string.templatelib import Interpolation, Template
print("Importing target module: pdb", file=stderr)
import pdb

TRIVIAL_TYPES = {int, str, float, bool, bytes, tuple, list, dict, set, type(None),}
def skip_trivial_type(obj_instance_or_class):
    if type(obj_instance_or_class) in TRIVIAL_TYPES:
        return True
    return False


import faulthandler
faulthandler.enable()
try:
    from _testcapi import set_nomemory as _set_nomemory
    _OOM_AVAILABLE = True
except ImportError:
    _OOM_AVAILABLE = False
    print("OOM mode requested but _testcapi.set_nomemory unavailable; running without injection", file=stderr)
# set_nomemory()/remove_mem_hooks() install/restore the allocation-failure hook by
# swapping the process-global allocator via PyMem_SetAllocator(), which is NOT
# thread-safe. Performing that swap inside the per-call/per-sequence OOM loops races
# any worker threads the fuzzed code spawned and corrupts the heap -- false-positive
# "crashes" (mimalloc asserts, _PyMem_DebugRawFree bad-ID, segvs). So install the hook
# EXACTLY ONCE here, before any fuzzed code runs, in a disarmed state, and thereafter
# only re-arm/disarm the failure WINDOW with set_nomemory() (which never swaps the
# allocator). _OOM_DISABLE is a start count no real run reaches, so every allocation
# passes through (injection effectively off).
_OOM_DISABLE = 2_000_000_000
if _OOM_AVAILABLE:
    _set_nomemory(_OOM_DISABLE, 0)

import sys
from _collections import OrderedDict, deque
from abc import ABCMeta
from collections import Counter
from queue import Queue
from random import randint
from string import printable

try:
    from _decimal import Decimal

    has__decimal = True
except ImportError:
    from decimal import Decimal

    has__decimal = False

sequences = [Queue, deque, frozenset, list, set, str, tuple]
bytes_ = [bytearray, bytes]
numbers = [Decimal, complex, float, int]
dicts = [Counter, OrderedDict, dict]
# dicts = [OrderedDict, dict]
bases = sequences + bytes_ + numbers + dicts + [object]

large_num = 2**64


class WeirdBase(ABCMeta):
    def __hash__(self):
        return randint(0, large_num)

    def __eq__(self, other):
        return False


weird_instances = dict()
weird_classes = dict()
for cls in bases:

    class weird_cls(cls, metaclass=WeirdBase):
        def add(self, *args, **kwargs):
            pass

        append = clear = close = write = sort = reversed = add

        def encode(self, *args, **kwargs):
            return b""

        def decode(self, *args, **kwargs):
            return ""

        format = getvalue = join = read = replace = strip = rstrip = decode

        def get(self, *args, **kwargs):
            return self

        open = pop = update = get

        def readlines(self, *args, **kwargs):
            return [""]

        rsplit = split = partition = rpartition = readlines

        def items(self):
            return {}.items()

        def keys(self):
            return {}.keys()

        def values(self):
            return {}.values()

    weird_cls.__name__ = f"weird_{cls.__name__}"
    weird_instances[f"weird_{cls.__name__}_empty"] = weird_cls()
    weird_classes[f"weird_{cls.__name__}"] = weird_cls

tricky_strs = (
    chr(0),
    chr(127),
    chr(255),
    chr(0x10FFFF),
    "𝒜",
    "\\x00" * 10,
    "A" * (2**16),
    "💻" * 2**10,
)

# We cannot create a Decimal larger than 10 ** 4300 with _pydecimal, only with _decimal
max_str_digits_adjustment = 1 if has__decimal else -1
big_int_for_decimal = 10 ** (sys.int_info.default_max_str_digits + max_str_digits_adjustment)

for cls in sequences:
    weird_instances[f"weird_{cls.__name__}_single"] = weird_classes[f"weird_{cls.__name__}"]("a")
    weird_instances[f"weird_{cls.__name__}_range"] = weird_classes[f"weird_{cls.__name__}"](
        range(20)
    )
    weird_instances[f"weird_{cls.__name__}_types"] = weird_classes[f"weird_{cls.__name__}"](bases)
    weird_instances[f"weird_{cls.__name__}_printable"] = weird_classes[f"weird_{cls.__name__}"](
        printable
    )
    weird_instances[f"weird_{cls.__name__}_special"] = weird_classes[f"weird_{cls.__name__}"](
        tricky_strs
    )
for cls in bytes_:
    weird_instances[f"weird_{cls.__name__}_bytes"] = weird_classes[f"weird_{cls.__name__}"](
        b"abcdefgh_" * 10
    )
for cls in numbers:
    weird_instances[f"weird_{cls.__name__}_sys_maxsize"] = weird_classes[f"weird_{cls.__name__}"](
        sys.maxsize
    )
    weird_instances[f"weird_{cls.__name__}_sys_maxsize_minus_one"] = weird_classes[
        f"weird_{cls.__name__}"
    ](sys.maxsize - 1)
    weird_instances[f"weird_{cls.__name__}_sys_maxsize_plus_one"] = weird_classes[
        f"weird_{cls.__name__}"
    ](sys.maxsize + 1)
    weird_instances[f"weird_{cls.__name__}_neg_sys_maxsize"] = weird_classes[
        f"weird_{cls.__name__}"
    ](-sys.maxsize)
    weird_instances[f"weird_{cls.__name__}_2**63-1"] = weird_classes[f"weird_{cls.__name__}"](
        2**63 - 1
    )
    weird_instances[f"weird_{cls.__name__}_2**63"] = weird_classes[f"weird_{cls.__name__}"](2**63)
    weird_instances[f"weird_{cls.__name__}_2**63+1"] = weird_classes[f"weird_{cls.__name__}"](
        2**63 + 1
    )
    weird_instances[f"weird_{cls.__name__}_-2**63+1"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**63) + 1
    )
    weird_instances[f"weird_{cls.__name__}_-2**63"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**63)
    )
    weird_instances[f"weird_{cls.__name__}_-2**63-1"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**63) - 1
    )
    weird_instances[f"weird_{cls.__name__}_2**31-1"] = weird_classes[f"weird_{cls.__name__}"](
        2**31 - 1
    )
    weird_instances[f"weird_{cls.__name__}_2**31"] = weird_classes[f"weird_{cls.__name__}"](2**31)
    weird_instances[f"weird_{cls.__name__}_2**31+1"] = weird_classes[f"weird_{cls.__name__}"](
        2**31 + 1
    )
    weird_instances[f"weird_{cls.__name__}_-2**31+1"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**31) + 1
    )
    weird_instances[f"weird_{cls.__name__}_-2**31"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**31)
    )
    weird_instances[f"weird_{cls.__name__}_-2**31-1"] = weird_classes[f"weird_{cls.__name__}"](
        -(2**31) - 1
    )
    if cls not in (float, complex) and hasattr(sys, "int_info"):
        weird_instances[f"weird_{cls.__name__}_10**default_max_str_digits+1"] = weird_classes[
            f"weird_{cls.__name__}"
        ](big_int_for_decimal)
for cls in dicts:
    weird_instances[f"weird_{cls.__name__}_basic"] = weird_classes[f"weird_{cls.__name__}"](
        {a: a for a in range(100)}
    )
    weird_instances[f"weird_{cls.__name__}_tricky_strs"] = weird_classes[f"weird_{cls.__name__}"](
        {a: a for a in tricky_strs}
    )


# Class with a __del__ side effect to attack the JIT optimizer
class FrameModifier:
    def __init__(self, var_name, new_value):
        # Store the name of the variable to target and its new value.
        self.var_name = var_name
        self.new_value = new_value
        # Announce creation for debugging the generated script
        print(f"  [FrameModifier created to target '{self.var_name}']", file=sys.stderr)

    def __del__(self):
        try:
            # On destruction, get the calling frame (1 level up).
            frame = sys._getframe(1)
            # Maliciously modify the local variable in that frame.
            print(
                f"  [Side Effect] In __del__: Modifying '{self.var_name}' to {self.new_value!r}",
                file=sys.stderr,
            )
            if self.var_name in frame.f_locals:
                frame.f_locals[self.var_name] = self.new_value
            elif (
                self.var_name.split(".")[0] in frame.f_locals and self.var_name.count(".") == 1
            ):  # instance_or_class.attribute
                instance_or_class_str, attr_str = self.var_name.split(".")
                setattr(frame.f_locals[instance_or_class_str], attr_str, self.new_value)
            else:  # module.instance_or_class.attribute
                module_str, instance_or_class_str, attr_str = self.var_name.split(".")
                instance_or_class = getattr(frame.f_locals[module_str], instance_or_class_str)
                setattr(instance_or_class, attr_str, self.new_value)
        except Exception as e:
            # Frame inspection can be tricky; don't crash in __del__.
            print(f"  [Side Effect] Error in FrameModifier.__del__: {e}", file=sys.stderr)


import abc
import builtins
import collections.abc
import itertools
import types
import typing
from functools import reduce
from operator import or_

abc_types = [cls for cls in abc.__dict__.values() if isinstance(cls, type)]
builtins_types = [cls for cls in builtins.__dict__.values() if isinstance(cls, type)]
collections_abc_types = [cls for cls in collections.abc.__dict__.values() if isinstance(cls, type)]
collections_types = [cls for cls in collections.__dict__.values() if isinstance(cls, type)]
itertools_types = [cls for cls in itertools.__dict__.values() if isinstance(cls, type)]
types_types = [cls for cls in types.__dict__.values() if isinstance(cls, type)]
typing_types = [cls for cls in typing.__dict__.values() if isinstance(cls, type)]

all_types = (
    abc_types
    + builtins_types
    + collections_abc_types
    + collections_types
    + itertools_types
    + types_types
    + typing_types
)
all_types = [t for t in all_types if not (isinstance(t, type) and issubclass(t, BaseException))]
big_union = reduce(or_, all_types, int)


import inspect
import types

tricky_cell = types.CellType(None)
tricky_simplenamespace = types.SimpleNamespace(dummy=None, cell=tricky_cell)
tricky_simplenamespace.dummy = tricky_simplenamespace
tricky_capsule = types.CapsuleType
tricky_module = types.ModuleType("tricky_module", "docs")
tricky_module2 = types.ModuleType("tricky_module2\\x00", "docs\\x00")
try:
    tricky_genericalias = types.GenericAlias(list, (int,))
except AttributeError:
    tricky_genericalias = None

tricky_dict = {}
if tricky_capsule:
    tricky_dict[tricky_capsule] = tricky_cell
if tricky_module:
    tricky_dict[tricky_module] = tricky_genericalias
tricky_dict["tricky_dict"] = tricky_dict
tricky_mappingproxy = types.MappingProxyType(tricky_dict)


def tricky_function(*args, **kwargs):
    if len(args) > 150:
        raise RecursionError("Fuzzer controlled depth")
    a = 1

    def b(x=a):
        v = x
        return v

    return tricky_function(*(args + (1,)), **kwargs)


tricky_lambda = lambda *args, **kwargs: tricky_lambda(*args, **kwargs)
tricky_classmethod = classmethod(tricky_lambda)
tricky_staticmethod = staticmethod(tricky_lambda)
tricky_property = property(tricky_lambda)
tricky_code = tricky_lambda.__code__
tricky_closure = tricky_function.__code__.co_freevars
tricky_classmethod_descriptor = types.ClassMethodDescriptorType  # This is the type itself


class TrickyDescriptor:
    def __get__(self, obj, objtype=None):
        return self

    def __set__(self, obj, value):
        try:
            obj.__dict__["_value_descriptor"] = value
        except AttributeError:
            pass

    def __delete__(self, obj):
        try:
            del obj.__dict__["_value_descriptor"]
        except (AttributeError, KeyError):
            pass


class TrickyMeta(type):
    @property
    def __signature__(self):
        raise AttributeError("Signature denied by TrickyMeta")

    def __mro_entries__(self, bases):
        return (object,)
        # return super().__mro_entries__(bases)


class TrickyClass(metaclass=TrickyMeta):
    tricky_descriptor = TrickyDescriptor()

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        self._value_init = None

    def __getattr__(self, name):
        if name == "crash_on_getattr":
            raise ValueError("getattr manipulated")
        return self


tricky_instance = TrickyClass()
try:
    tricky_frame = inspect.currentframe()
    if tricky_frame:  # currentframe() can be None
        # tricky_frame.f_builtins.update(tricky_dict)
        tricky_frame.f_globals.update(tricky_dict)
        tricky_frame.f_locals.update(tricky_dict)
except RuntimeError:
    tricky_frame = None


try:
    1 / 0
except ZeroDivisionError as e:
    tricky_traceback = e.__traceback__
else:
    tricky_traceback = None


# tricky_generator = (x for x in itertools.count())
tricky_list_with_cycle = [[]] * 6 + []
tricky_list_with_cycle[0].append(tricky_list_with_cycle)
tricky_list_with_cycle[-1].append(tricky_list_with_cycle)
tricky_list_with_cycle.append(tricky_list_with_cycle)
if tricky_list_with_cycle[0] and tricky_list_with_cycle[0][0] is tricky_list_with_cycle:
    tricky_list_with_cycle[0][0].append(tricky_list_with_cycle)


def errback(*args, **kw):
    raise ValueError('errback called')


class Liar1:
    def __eq__(self, other):
        return True

class Liar2:
    def __eq__(self, other):
        return False

liar1, liar2 = Liar1(), Liar2()

class Evil:
    def __eq__(self, other):
        for attr in dir(other):
            try: other.__dict__[attr] = errback
            except: pass

evil = Evil()


# Define a custom exception to distinguish our check from others.
class JITCorrectnessError(AssertionError): pass

# This function is called only once, so it will not be JIT-compiled.
def no_jit_harness(func, *args, **kwargs):
    return func(*args, **kwargs)

# This function calls its target in a loop to make it 'hot' for the JIT.
def jit_harness(func, iterations, *args, **kwargs):
    print(f"[+] Warming up {func.__name__} for {iterations} iterations...", file=stderr)
    for _ in range(iterations):
        func(*args, **kwargs)
    print("[+] Warm-up complete.", file=stderr)

# Helper for correctness testing that handles NaN, lambdas, and complex numbers.
import math
import types
def compare_results(a, b):
    if isinstance(a, types.FunctionType) and a.__name__ == '<lambda>' and \
       isinstance(b, types.FunctionType) and b.__name__ == '<lambda>':
        return True # Treat two lambdas as equal for our purposes
    if isinstance(a, complex) and isinstance(b, complex):
        a_real_nan = math.isnan(a.real)
        b_real_nan = math.isnan(b.real)
        a_imag_nan = math.isnan(a.imag)
        b_imag_nan = math.isnan(b.imag)
        real_match = (a.real == b.real) or (a_real_nan and b_real_nan)
        imag_match = (a.imag == b.imag) or (a_imag_nan and b_imag_nan)
        return real_match and imag_match
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, object) and isinstance(b, object):
        return True
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
        return all(compare_results(x, y) for x, y in zip(a, b))
    return a == b

SENTINEL_VALUE = object()

def callMethod(prefix, obj_to_call, method_name, *arguments, verbose=True):
    func_display_name = f"pdb.{method_name}()" if obj_to_call is pdb else f"{obj_to_call.__class__.__name__}.{method_name}()"
    message = f"[{prefix}] {func_display_name}"
    if verbose:
        print(message, file=stderr)
    result = SENTINEL_VALUE
    try:
        func_to_run = getattr(obj_to_call, method_name)
        for _ in range(int(3)):
            result = func_to_run(*arguments)
    except (Exception, SystemExit, KeyboardInterrupt) as err:
        try:
            errmsg = repr(err)
        except Exception as e_repr:
            errmsg = f'Error during repr: {e_repr.__class__.__name__}'
        errmsg = errmsg.encode('ASCII', 'replace').decode('ASCII')
        if verbose:
            print(f"[{prefix}] {func_display_name} => EXCEPTION: {err.__class__.__name__}: {errmsg}", file=stderr)
        result = SENTINEL_VALUE
    if verbose:
        print(f"[{prefix}] -explicit garbage collection-", file=stderr)
    collect()
    if result is not SENTINEL_VALUE:
        fuzzer_threads_alive.append(Thread(target=func_to_run, args=arguments, name=message))
    return result

def callFunc(prefix, func_name_str, *arguments, verbose=True):
    return callMethod(prefix, pdb, func_name_str, *arguments, verbose=verbose)

_OOM_MAX_START = 1000
_OOM_VERBOSE = True

def oom_call(label, func, *args, **kwargs):
    # Dense OOM sweep: fail every allocation from #_start onward, one
    # _start per iteration. The per-call marker (printed once, before the
    # sweep) identifies which invocation was running if a crash follows --
    # more reliable than the faulthandler frame, which is often an
    # incidental allocation rather than the fuzzed target. MemoryError is
    # the expected outcome and is swallowed silently; SystemError is
    # surfaced (PyCFunction contract violations); a real crash
    # (segfault/abort) terminates the process, the signal fusil scores.
    # The inner finally DISARMS injection (set_nomemory with an unreachable start)
    # so the except clauses allocate freely, WITHOUT swapping the allocator -- the
    # swap is not thread-safe and would corrupt the heap if the fuzzed call left
    # worker threads running (see the one-time install note above).
    if not _OOM_AVAILABLE or func is None:
        return
    print("[OOM] " + label, file=stderr)
    for _start in range(_OOM_MAX_START):
        if _OOM_VERBOSE:
            print("[OOM]   start=" + str(_start), file=stderr)
        _set_nomemory(_start, 0)
        try:
            try:
                func(*args, **kwargs)
            finally:
                _set_nomemory(_OOM_DISABLE, 0)
        except MemoryError:
            pass
        except SystemError:
            print("[OOM] SystemError in " + label, file=stderr)
        except BaseException:
            pass

_OOM_WINDOW = 8

def oom_run(label, thunk, window=_OOM_WINDOW):
    # Stateful OOM sequence (Phase 4): sweep a bounded failure window
    # across a multi-step thunk so a failure in one step can corrupt
    # state a later step trips over. set_nomemory(start, start+window)
    # fails `window` allocations then resumes succeeding, so steps after
    # the burst run on the damaged state (window == 0 -> fail forever,
    # the legacy single-call semantics). `window` defaults to _OOM_WINDOW
    # but is passed per-sequence when --oom-seq-randomize is set. The thunk
    # guards each step internally so the tail still runs after an earlier
    # step raises; a real crash (segfault/abort) terminates the process and
    # is scored.
    if not _OOM_AVAILABLE:
        try:
            thunk()
        except BaseException:
            pass
        return
    print("[OOM-SEQ] " + label + " window=" + str(window), file=stderr)
    for _start in range(_OOM_MAX_START):
        if _OOM_VERBOSE:
            print("[OOM-SEQ]   start=" + str(_start) + " window=" + str(window), file=stderr)
        if window > 0:
            _set_nomemory(_start, _start + window)
        else:
            _set_nomemory(_start, 0)
        try:
            try:
                thunk()
            finally:
                _set_nomemory(_OOM_DISABLE, 0)
        except MemoryError:
            pass
        except SystemError:
            print("[OOM-SEQ] SystemError in " + label, file=stderr)
        except BaseException:
            pass

fuzz_target_module = pdb

fuzzer_threads_alive = []
fuzzer_async_tasks = []


# FUSIL_BOILERPLATE_END


import sys
from random import choice, randint, random, sample
from sys import stderr, path as sys_path


print("--- Fuzzing 22 functions in pdb ---", file=stderr)
# OOM sequence: runcall
def _oom_seq_f1():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:runcall", file=stderr)
        getattr(fuzz_target_module, "runcall", None)(
        )
    except BaseException:
        pass
oom_run("f1:pdb[runcall]", _oom_seq_f1, window=3)

# OOM sequence: attach > post_mortem
def _oom_seq_f2():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:attach", file=stderr)
        getattr(fuzz_target_module, "attach", None)(
            False,
            "T[\x8E\xDF\x88",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:post_mortem", file=stderr)
        getattr(fuzz_target_module, "post_mortem", None)(
        )
    except BaseException:
        pass
oom_run("f2:pdb[attach>post_mortem]", _oom_seq_f2, window=7)

# OOM sequence: pm
def _oom_seq_f3():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:pm", file=stderr)
        getattr(fuzz_target_module, "pm", None)(
        )
    except BaseException:
        pass
oom_run("f3:pdb[pm]", _oom_seq_f3, window=8)

# OOM sequence: pm
def _oom_seq_f4():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:pm", file=stderr)
        getattr(fuzz_target_module, "pm", None)(
        )
    except BaseException:
        pass
oom_run("f4:pdb[pm]", _oom_seq_f4, window=1)

# OOM sequence: post_mortem > set_trace_async > help > set_trace > pm > attach
def _oom_seq_f5():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:post_mortem", file=stderr)
        getattr(fuzz_target_module, "post_mortem", None)(
            11,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:set_trace_async", file=stderr)
        getattr(fuzz_target_module, "set_trace_async", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:help", file=stderr)
        getattr(fuzz_target_module, "help", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:set_trace", file=stderr)
        getattr(fuzz_target_module, "set_trace", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:pm", file=stderr)
        getattr(fuzz_target_module, "pm", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:attach", file=stderr)
        getattr(fuzz_target_module, "attach", None)(
            4.1,
        )
    except BaseException:
        pass
oom_run("f5:pdb[post_mortem>set_trace_async>help>set_trace>pm>attach]", _oom_seq_f5, window=6)

# OOM sequence: get_default_backend > exit_with_permission_help_text > runctx > contextmanager > attach
def _oom_seq_f6():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:get_default_backend", file=stderr)
        getattr(fuzz_target_module, "get_default_backend", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:exit_with_permission_help_text", file=stderr)
        getattr(fuzz_target_module, "exit_with_permission_help_text", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:runctx", file=stderr)
        getattr(fuzz_target_module, "runctx", None)(
            list[weird_classes['weird_list']] | weird_classes['weird_bytearray'] | big_union,
            weird_instances['weird_float_2**63+1'],
            errback,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:contextmanager", file=stderr)
        getattr(fuzz_target_module, "contextmanager", None)(
            b"\xD1\x26\xCE\x6E\x54\x90\x33\x6B\x22\xE0\xF5\x7F",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:attach", file=stderr)
        getattr(fuzz_target_module, "attach", None)(
            "",
        )
    except BaseException:
        pass
oom_run("f6:pdb[get_default_backend>exit_with_permission_help_text>runctx>contextmanager>attach]", _oom_seq_f6, window=4)

# OOM sequence: runctx > pm > _pyrepl_available > post_mortem > get_default_backend > parse_args
def _oom_seq_f7():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:runctx", file=stderr)
        getattr(fuzz_target_module, "runctx", None)(
            "AzL8N7jzV8MHTW/A/..//9Isajeq/NKB2j9xnZw8FOB/Y_08/",
            tuple[weird_classes['weird_float']] | weird_classes['weird_object'] | big_union,
            "ozO7HPuxv.Rs_vpaPI1y1pO8YKFdbEzQf-4PVjJTFbrD/hUDj1LsGoKLG/_/c",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:pm", file=stderr)
        getattr(fuzz_target_module, "pm", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:_pyrepl_available", file=stderr)
        getattr(fuzz_target_module, "_pyrepl_available", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:post_mortem", file=stderr)
        getattr(fuzz_target_module, "post_mortem", None)(
            18.3,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:get_default_backend", file=stderr)
        getattr(fuzz_target_module, "get_default_backend", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:parse_args", file=stderr)
        getattr(fuzz_target_module, "parse_args", None)(
        )
    except BaseException:
        pass
oom_run("f7:pdb[runctx>pm>_pyrepl_available>post_mortem>get_default_backend>parse_args]", _oom_seq_f7, window=2)

# OOM sequence: contextmanager > _pyrepl_available > post_mortem > set_trace
def _oom_seq_f8():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:contextmanager", file=stderr)
        getattr(fuzz_target_module, "contextmanager", None)(
            bytearray(b"test"),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:_pyrepl_available", file=stderr)
        getattr(fuzz_target_module, "_pyrepl_available", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:post_mortem", file=stderr)
        getattr(fuzz_target_module, "post_mortem", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:set_trace", file=stderr)
        getattr(fuzz_target_module, "set_trace", None)(
        )
    except BaseException:
        pass
oom_run("f8:pdb[contextmanager>_pyrepl_available>post_mortem>set_trace]", _oom_seq_f8, window=2)

# OOM sequence: _post_mortem > find_function
def _oom_seq_f9():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_post_mortem", file=stderr)
        getattr(fuzz_target_module, "_post_mortem", None)(
            sys.maxsize + 1,
            Exception('fuzzer_generated_exception'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:find_function", file=stderr)
        getattr(fuzz_target_module, "find_function", None)(
            8,
            "~\x93\x9A\x8E\xE4\xE2\xC4\xA0\x92",
        )
    except BaseException:
        pass
oom_run("f9:pdb[_post_mortem>find_function]", _oom_seq_f9, window=7)

# OOM sequence: _pyrepl_available > lasti2lineno > post_mortem
def _oom_seq_f10():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_pyrepl_available", file=stderr)
        getattr(fuzz_target_module, "_pyrepl_available", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:lasti2lineno", file=stderr)
        getattr(fuzz_target_module, "lasti2lineno", None)(
            weird_classes['weird_float'],
            True,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:post_mortem", file=stderr)
        getattr(fuzz_target_module, "post_mortem", None)(
        )
    except BaseException:
        pass
oom_run("f10:pdb[_pyrepl_available>lasti2lineno>post_mortem]", _oom_seq_f10, window=3)


print("--- OOM-fuzzing 14 classes in pdb ---", file=stderr)
# OOM sweep: ExitStack() constructor
oom_call("oc1:pdb.ExitStack", getattr(fuzz_target_module, "ExitStack", None),
)

oom_inst_oc1_exitstack = None
try:
    oom_inst_oc1_exitstack = callFunc("oc1_init", "ExitStack",
    )
except Exception:
    oom_inst_oc1_exitstack = None

if oom_inst_oc1_exitstack is not None and oom_inst_oc1_exitstack is not SENTINEL_VALUE:
    # OOM sequence on ExitStack: __reduce__
    def _oom_seq_oc1():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__reduce__", file=stderr)
            getattr(oom_inst_oc1_exitstack, "__reduce__", None)(
            )
        except BaseException:
            pass
    oom_run("oc1:pdb.ExitStack[__reduce__]", _oom_seq_oc1, window=3)

    del oom_inst_oc1_exitstack
    collect()

# OOM sweep: _ScriptTarget() constructor
oom_call("oc2:pdb._ScriptTarget", getattr(fuzz_target_module, "_ScriptTarget", None),
    2,
)

oom_inst_oc2__scripttarget = None
try:
    oom_inst_oc2__scripttarget = callFunc("oc2_init", "_ScriptTarget",
        Template("\x00", Interpolation(weird_instances['weird_complex_2**31'], "name")),
    )
except Exception:
    oom_inst_oc2__scripttarget = None

if oom_inst_oc2__scripttarget is not None and oom_inst_oc2__scripttarget is not SENTINEL_VALUE:
    # OOM sequence on _ScriptTarget: __getstate__ > __hash__ > __lt__ > __init_subclass__ > _safe_realpath
    def _oom_seq_oc2():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__getstate__", file=stderr)
            getattr(oom_inst_oc2__scripttarget, "__getstate__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__hash__", file=stderr)
            getattr(oom_inst_oc2__scripttarget, "__hash__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__lt__", file=stderr)
            getattr(oom_inst_oc2__scripttarget, "__lt__", None)(
                errback,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__init_subclass__", file=stderr)
            getattr(oom_inst_oc2__scripttarget, "__init_subclass__", None)(
                bytearray(b"abc\xe9\xff"),
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:_safe_realpath", file=stderr)
            getattr(oom_inst_oc2__scripttarget, "_safe_realpath", None)(
                tricky_function,
            )
        except BaseException:
            pass
    oom_run("oc2:pdb._ScriptTarget[__getstate__>__hash__>__lt__>__init_subclass__>_safe_realpath]", _oom_seq_oc2, window=1)

    del oom_inst_oc2__scripttarget
    collect()

# OOM sweep: _ZipTarget() constructor
oom_call("oc3:pdb._ZipTarget", getattr(fuzz_target_module, "_ZipTarget", None),
    errback,
)

oom_inst_oc3__ziptarget = None
try:
    oom_inst_oc3__ziptarget = callFunc("oc3_init", "_ZipTarget",
        "fW.",
    )
except Exception:
    oom_inst_oc3__ziptarget = None

if oom_inst_oc3__ziptarget is not None and oom_inst_oc3__ziptarget is not SENTINEL_VALUE:
    # OOM sequence on _ZipTarget: __new__ > __reduce_ex__ > __sizeof__ > __le__ > __new__ > __ge__
    def _oom_seq_oc3():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__new__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__new__", None)(
                '/tmp/fusil-fixtures/fusil_fixture.bin',
                Exception('fuzzer_generated_exception'),
                Exception('fuzzer_generated_exception'),
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__reduce_ex__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__reduce_ex__", None)(
                414.94,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__sizeof__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__sizeof__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__le__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__le__", None)(
                -152806194547,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:__new__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__new__", None)(
                "\uDC80",
                '/tmp/fusil-fixtures/fusil_fixture.bin',
                "Q3Ye5BT7slKWXv/2lhF/Crjoz.BG9NXlt_7k/Ln1grNSjKR/y/",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m6:__ge__", file=stderr)
            getattr(oom_inst_oc3__ziptarget, "__ge__", None)(
                -sys.float_info.min / 2,
            )
        except BaseException:
            pass
    oom_run("oc3:pdb._ZipTarget[__new__>__reduce_ex__>__sizeof__>__le__>__new__>__ge__]", _oom_seq_oc3, window=1)

    del oom_inst_oc3__ziptarget
    collect()

# OOM sweep: _PdbInteractiveConsole() constructor
oom_call("oc4:pdb._PdbInteractiveConsole", getattr(fuzz_target_module, "_PdbInteractiveConsole", None),
    '/tmp/fusil-fixtures/fusil_fixture.bin',
    "\u36CE\uDBD8",
)

oom_inst_oc4__pdbinteractiveconsole = None
try:
    oom_inst_oc4__pdbinteractiveconsole = callFunc("oc4_init", "_PdbInteractiveConsole",
        liar1,
        -17,
    )
except Exception:
    oom_inst_oc4__pdbinteractiveconsole = None

if oom_inst_oc4__pdbinteractiveconsole is not None and oom_inst_oc4__pdbinteractiveconsole is not SENTINEL_VALUE:
    # OOM sequence on _PdbInteractiveConsole: interact > __dir__ > __reduce__ > __dir__ > __delattr__ > __le__
    def _oom_seq_oc4():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:interact", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "interact", None)(
                r"h.tglcL+y.I.\bc\bkLTlu",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__dir__", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "__dir__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__reduce__", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "__reduce__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__dir__", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "__dir__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:__delattr__", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "__delattr__", None)(
                Template("\x00", Interpolation(weird_instances['weird_Decimal_2**31'], "name")),
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m6:__le__", file=stderr)
            getattr(oom_inst_oc4__pdbinteractiveconsole, "__le__", None)(
                b"\xFA\x67\x39\x3F\x50\x5C\x74\xA4\x3E\xAE",
            )
        except BaseException:
            pass
    oom_run("oc4:pdb._PdbInteractiveConsole[interact>__dir__>__reduce__>__dir__>__delattr__>__le__]", _oom_seq_oc4, window=5)

    del oom_inst_oc4__pdbinteractiveconsole
    collect()

# OOM sweep: closing() constructor
oom_call("oc5:pdb.closing", getattr(fuzz_target_module, "closing", None),
    errback,
)

oom_inst_oc5_closing = None
try:
    oom_inst_oc5_closing = callFunc("oc5_init", "closing",
        Evil(),
    )
except Exception:
    oom_inst_oc5_closing = None

if oom_inst_oc5_closing is not None and oom_inst_oc5_closing is not SENTINEL_VALUE:
    # OOM sequence on closing: __init__
    def _oom_seq_oc5():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__init__", file=stderr)
            getattr(oom_inst_oc5_closing, "__init__", None)(
                "\u9062\u8D98\uDE09\uACB0\u5AD3\u04D7\u1BEE\u0DF8\u0388\uF8FC\u93BC\u4D06\uC63D\uA8B3\uCE01\u20A8\uF4C3",
            )
        except BaseException:
            pass
    oom_run("oc5:pdb.closing[__init__]", _oom_seq_oc5, window=7)

    del oom_inst_oc5_closing
    collect()

print("--- Starting and Joining Fuzzer Threads ---", file=stderr)
for t_obj in fuzzer_threads_alive:
    try:
        print(f"Starting thread: {t_obj.name}", file=stderr)
        t_obj.start()
    except Exception as e_thread_start:
        print(f"Failed to start thread {t_obj.name}: {e_thread_start.__class__.__name__}", file=stderr)
for t_obj in fuzzer_threads_alive:
    try:
        print(f"Joining thread: {t_obj.name}", file=stderr)
        t_obj.join(timeout=1.0) # Add timeout to join
    except Exception as e_thread_join:
        print(f"Failed to join thread {t_obj.name}: {e_thread_join.__class__.__name__}", file=stderr)

print("--- Running Fuzzer Async Tasks ---", file=stderr)
async def main_async_fuzzer_tasks():
    if not fuzzer_async_tasks: return
    task_objects = [asyncio.to_thread(func) for func in fuzzer_async_tasks]
    await asyncio.gather(*task_objects, return_exceptions=True)

runner = asyncio.Runner()
try:
    runner.run(main_async_fuzzer_tasks())
except Exception as e_async_runner_run:
    print(f'Exception in async runner: {e_async_runner_run.__class__.__name__} {e_async_runner_run}')
finally:
    runner.close()

