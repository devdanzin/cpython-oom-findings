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
seed(194716949)

from string.templatelib import Interpolation, Template
print("Importing target module: code", file=stderr)
import code

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
    func_display_name = f"code.{method_name}()" if obj_to_call is code else f"{obj_to_call.__class__.__name__}.{method_name}()"
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
    return callMethod(prefix, code, func_name_str, *arguments, verbose=verbose)

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

fuzz_target_module = code

fuzzer_threads_alive = []
fuzzer_async_tasks = []


# FUSIL_BOILERPLATE_END


import sys
from random import choice, randint, random, sample
from sys import stderr, path as sys_path


print("--- Fuzzing 2 functions in code ---", file=stderr)
# OOM sequence: interact
def _oom_seq_f1():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
        )
    except BaseException:
        pass
oom_run("f1:code[interact]", _oom_seq_f1, window=2)

# OOM sequence: interact > compile_command
def _oom_seq_f2():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            '/tmp/fusil-fixtures/fusil_fixture.bin',
            weird_instances['weird_deque_single'],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            709934420209468974,
            46452,
            "UEKzgAVVqxUAn30ppfa4LpLebnMVRj-LCVXZG0I5rJiu2-/MJjKf4VRbhBS94M96h84TOQ8PlKBl/",
        )
    except BaseException:
        pass
oom_run("f2:code[interact>compile_command]", _oom_seq_f2, window=3)

# OOM sequence: compile_command > interact
def _oom_seq_f3():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            lambda: None,
            list[weird_classes['weird_deque']],
            "\udbff\udfff",
            dict[weird_classes['weird_dict']] | weird_classes['weird_OrderedDict'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            list[weird_classes['weird_set']] | weird_classes['weird_list'] | big_union,
            "\x00",
        )
    except BaseException:
        pass
oom_run("f3:code[compile_command>interact]", _oom_seq_f3, window=5)

# OOM sequence: compile_command > interact
def _oom_seq_f4():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            b"\xC5\x64\x74\x6D\x6B",
            tuple[weird_classes['weird_Counter']] | weird_classes['weird_OrderedDict'] | big_union,
            dict[weird_classes['weird_float']],
            int,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
        )
    except BaseException:
        pass
oom_run("f4:code[compile_command>interact]", _oom_seq_f4, window=7)

# OOM sequence: interact > interact > compile_command
def _oom_seq_f5():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            '/tmp/fusil-fixtures/fusil_fixture.txt',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            list[weird_classes['weird_set']] | weird_classes['weird_bytearray'] | big_union,
            None,
            '/tmp/fusil-fixtures/fusil_fixture.txt',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            weird_classes['weird_int'],
            [tricky_instance,
             weird_instances['weird_list_printable'],
             memoryview(bytearray(b"abc\xe9\xff")),
             -313138972229109797,
             -78.304],
        )
    except BaseException:
        pass
oom_run("f5:code[interact>interact>compile_command]", _oom_seq_f5, window=8)

# OOM sequence: interact > interact > interact > compile_command > interact
def _oom_seq_f6():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            "\U0010FFFF",
            "\xE9\xA7\xA3r",
            tuple[weird_classes['weird_Decimal']],
            b"\x98\x4B\x17\x9C",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            8,
            list[weird_classes['weird_int']],
            b"\xBE\x47\x52\x3C\x1B\x0A\x50\x2E\x5A\xA8",
            Liar1,
            Exception('fuzzer_generated_exception'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            dict[weird_classes['weird_list']] | weird_classes['weird_tuple'] | big_union,
            list[weird_classes['weird_list']],
            {False: Exception('fuzzer_generated_exception'),
             Exception('fuzzer_generated_exception'): dict[weird_classes['weird_tuple']] | weird_classes['weird_deque'] | big_union,
             b"\x17": tricky_list_with_cycle,
             983367198840924: weird_classes['weird_Counter'],
             "\x97\x92mi\xA5": weird_classes['weird_int']},
            -6,
            "\u5179\u28CE\uF797\u8514\u2AC3\uA099\uDB7E\u954F\u66DB\u7B96\u6982\u24FE\uBE3D\u239E\u9F0A\u0AC0",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            19,
            tricky_property,
            errback,
            Evil(),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            bytearray(b"abc\xe9\xff"),
            "\x02",
            Liar1,
            r"bDh.Ob.p*\sBFajnarnj..S\sm.LfT*n\sQExHvn\s\Az\wG\bHO?N",
            tuple[weird_classes['weird_complex']] | weird_classes['weird_complex'] | big_union,
        )
    except BaseException:
        pass
oom_run("f6:code[interact>interact>interact>compile_command>interact]", _oom_seq_f6, window=5)

# OOM sequence: compile_command > interact > interact > compile_command
def _oom_seq_f7():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            4326135571741524068,
            Exception('fuzzer_generated_exception'),
            r"MZxsYDGfm.uPVBrzc.\dbAj+H..mpD",
            "9ns7l2AP0ozZKfuZ18p-41Q.Emjz681SnnxtJPYnjBj-_K05OfE4LEBOfGG7mcqbydp-_OTxw03-GsDfaDyQQxMbE/v",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            tricky_traceback,
            -3,
            TrickyDescriptor,
            288427578217,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            '/tmp/fusil-fixtures/fusil_fixture.bin',
            r"HGG*.E.\d\sIoQxnjTX\wS?S\AE+bx\DQHGjQ\s\b\DMbo.?",
            Exception('fuzzer_generated_exception'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            memoryview(b"A" * 2**8),
            True,
            "\u398A\uB2D0\u5824\u7B42\u7CFE\uA3F8\uF872\uB6E0\u24D7\uF512\u0AA0\u9BDE\u3E3A\u710E\u4B89\uF4FD\uBC11\u6588\u5B7B",
            "xum\x90c~\xF7Y\x1AQ\x0F\xD7\"",
        )
    except BaseException:
        pass
oom_run("f7:code[compile_command>interact>interact>compile_command]", _oom_seq_f7, window=8)

# OOM sequence: compile_command > compile_command > interact > compile_command > compile_command > interact
def _oom_seq_f8():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            r"KF\sg.\b",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            "66.mB7a8KyC53xhL/.4.eXB-",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            b"\x5C",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            "zsaEJg_z7j/oerc_Ft5xEKCrUlYmKjxY1pug5mxvgManw0en_YeZBK2LtiQ8nZu/ke/uHrwj1Al/Aje/.//J",
            None,
            Exception('fuzzer_generated_exception'),
            dict[weird_classes['weird_deque']] | weird_classes['weird_float'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            errback,
            tuple[weird_classes['weird_Queue']] | weird_classes['weird_dict'] | big_union,
            {r"HCyLo+",
             '/tmp/fusil-fixtures/fusil_fixture.bin',
             "4W",
             "Xr7hKGTUm7bZps5wr5qgE8v558YjMJYjLReNMf9chW6RgtOPYslvs6h006M6ny1vGiEZkx.z4b/.",
             errback,
             False},
            Evil(),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            '/tmp/fusil-fixtures/fusil_fixture.bin',
            "yV\x9A\x98Mr\xF6`\xA4",
            Template("\x00", Interpolation(weird_classes['weird_Queue'], "name")),
            b"\x00" * (2**16),
        )
    except BaseException:
        pass
oom_run("f8:code[compile_command>compile_command>interact>compile_command>compile_command>interact]", _oom_seq_f8, window=8)

# OOM sequence: compile_command > compile_command > interact > compile_command > interact > interact
def _oom_seq_f9():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            weird_classes['weird_frozenset'],
            "\x84\xD4X\xB7$\xC5\xA5",
            weird_classes['weird_bytes'],
            False,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            dict[weird_classes['weird_bytes']] | weird_classes['weird_list'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            r"\SJq.Kohcx.O\wg\sdwquHd?l\D.yW*NSlUj",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            memoryview(b"abc\xe9\xff"),
            "//088lC/y_HokNgfdEU1HSa9HYTQcQPEB/OyKlN//c",
            "\U0010FFFF",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            "zW1wjqv2Lqoy3hMollkwNkmWBYiEEUmCLjxTiIfEbVdKZpgwPAYjIJ3JE3kq_FHwzfiwDZrCNVyS/tW3/./GGFJWQJtj/S/",
            "\u3358\u646F\u1492\uC4BD\u073F\x17\u6B31\u7ACA\u626C\u8850\u4912\u2E5D\uCCBB\uFF60\u4842\u744D\u2F47",
            False,
            "\x89\xBD\xDC\x9F\x12\xEA>)\x9F",
        )
    except BaseException:
        pass
oom_run("f9:code[compile_command>compile_command>interact>compile_command>interact>interact]", _oom_seq_f9, window=2)

# OOM sequence: compile_command > interact > interact
def _oom_seq_f10():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:compile_command", file=stderr)
        getattr(fuzz_target_module, "compile_command", None)(
            dict[weird_classes['weird_bytes']],
            weird_instances['weird_float_sys_maxsize_minus_one'],
            (-3,
             -1,
             '/tmp/fusil-fixtures/fusil_fixture.txt'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            weird_classes['weird_list'],
            -14,
            {Exception('fuzzer_generated_exception'): chr(127)},
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:interact", file=stderr)
        getattr(fuzz_target_module, "interact", None)(
            dict[weird_classes['weird_float']],
        )
    except BaseException:
        pass
oom_run("f10:code[compile_command>interact>interact]", _oom_seq_f10, window=3)


print("--- OOM-fuzzing 4 classes in code ---", file=stderr)
# OOM sweep: CommandCompiler() constructor
oom_call("oc1:code.CommandCompiler", getattr(fuzz_target_module, "CommandCompiler", None),
)

oom_inst_oc1_commandcompiler = None
try:
    oom_inst_oc1_commandcompiler = callFunc("oc1_init", "CommandCompiler",
    )
except Exception:
    oom_inst_oc1_commandcompiler = None

if oom_inst_oc1_commandcompiler is not None and oom_inst_oc1_commandcompiler is not SENTINEL_VALUE:
    # OOM sequence on CommandCompiler: __hash__ > __repr__ > __sizeof__ > __format__ > __format__ > __init__
    def _oom_seq_oc1():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__hash__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__hash__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__repr__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__repr__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__sizeof__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__sizeof__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__format__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__format__", None)(
                TrickyClass,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:__format__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__format__", None)(
                "\xDC$",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m6:__init__", file=stderr)
            getattr(oom_inst_oc1_commandcompiler, "__init__", None)(
            )
        except BaseException:
            pass
    oom_run("oc1:code.CommandCompiler[__hash__>__repr__>__sizeof__>__format__>__format__>__init__]", _oom_seq_oc1, window=4)

    del oom_inst_oc1_commandcompiler
    collect()

# OOM sweep: InteractiveInterpreter() constructor
oom_call("oc2:code.InteractiveInterpreter", getattr(fuzz_target_module, "InteractiveInterpreter", None),
    errback,
)

oom_inst_oc2_interactiveinterpreter = None
try:
    oom_inst_oc2_interactiveinterpreter = callFunc("oc2_init", "InteractiveInterpreter",
        memoryview(bytearray(b"abc\xe9\xff")),
    )
except Exception:
    oom_inst_oc2_interactiveinterpreter = None

if oom_inst_oc2_interactiveinterpreter is not None and oom_inst_oc2_interactiveinterpreter is not SENTINEL_VALUE:
    # OOM sequence on InteractiveInterpreter: __eq__
    def _oom_seq_oc2():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__eq__", file=stderr)
            getattr(oom_inst_oc2_interactiveinterpreter, "__eq__", None)(
                "\x02[\xED\x1A\x95\x19\xC9\xD5\x90Uw",
            )
        except BaseException:
            pass
    oom_run("oc2:code.InteractiveInterpreter[__eq__]", _oom_seq_oc2, window=4)

    del oom_inst_oc2_interactiveinterpreter
    collect()

# OOM sweep: InteractiveInterpreter() constructor
oom_call("oc3:code.InteractiveInterpreter", getattr(fuzz_target_module, "InteractiveInterpreter", None),
)

oom_inst_oc3_interactiveinterpreter = None
try:
    oom_inst_oc3_interactiveinterpreter = callFunc("oc3_init", "InteractiveInterpreter",
    )
except Exception:
    oom_inst_oc3_interactiveinterpreter = None

if oom_inst_oc3_interactiveinterpreter is not None and oom_inst_oc3_interactiveinterpreter is not SENTINEL_VALUE:
    # OOM sequence on InteractiveInterpreter: runsource > showtraceback > __hash__
    def _oom_seq_oc3():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:runsource", file=stderr)
            getattr(oom_inst_oc3_interactiveinterpreter, "runsource", None)(
                "\x00" * 10,
                TrickyClass,
                dict[weird_classes['weird_Decimal']] | weird_classes['weird_dict'] | big_union,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:showtraceback", file=stderr)
            getattr(oom_inst_oc3_interactiveinterpreter, "showtraceback", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__hash__", file=stderr)
            getattr(oom_inst_oc3_interactiveinterpreter, "__hash__", None)(
            )
        except BaseException:
            pass
    oom_run("oc3:code.InteractiveInterpreter[runsource>showtraceback>__hash__]", _oom_seq_oc3, window=5)

    del oom_inst_oc3_interactiveinterpreter
    collect()

# OOM sweep: InteractiveInterpreter() constructor
oom_call("oc4:code.InteractiveInterpreter", getattr(fuzz_target_module, "InteractiveInterpreter", None),
    -4,
)

oom_inst_oc4_interactiveinterpreter = None
try:
    oom_inst_oc4_interactiveinterpreter = callFunc("oc4_init", "InteractiveInterpreter",
        weird_classes['weird_bytes'],
    )
except Exception:
    oom_inst_oc4_interactiveinterpreter = None

if oom_inst_oc4_interactiveinterpreter is not None and oom_inst_oc4_interactiveinterpreter is not SENTINEL_VALUE:
    # OOM sequence on InteractiveInterpreter: __init__ > __le__
    def _oom_seq_oc4():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__init__", file=stderr)
            getattr(oom_inst_oc4_interactiveinterpreter, "__init__", None)(
                {False: errback,
                 "\xA9s\x84,\x8C": int,
                 True: lambda *args, **kwargs: 1/0,
                 errback: lambda *args, **kwargs: 1/0,
                 "yD0RukKtN/": weird_instances['weird_list_printable'],
                 '/tmp/fusil-fixtures/fusil_fixture.txt': dict[weird_classes['weird_Decimal']] | weird_classes['weird_float'] | big_union,
                 errback: -76.1,
                 "cvAf-BDftv2Y1kQ.56AKgdFZ-2LZs/jptGBe/Eh/Zhk": inspect,
                 b"": "\U0010FFFF"},
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__le__", file=stderr)
            getattr(oom_inst_oc4_interactiveinterpreter, "__le__", None)(
                "\x00",
            )
        except BaseException:
            pass
    oom_run("oc4:code.InteractiveInterpreter[__init__>__le__]", _oom_seq_oc4, window=2)

    del oom_inst_oc4_interactiveinterpreter
    collect()

# OOM sweep: InteractiveConsole() constructor
oom_call("oc5:code.InteractiveConsole", getattr(fuzz_target_module, "InteractiveConsole", None),
    errback,
)

oom_inst_oc5_interactiveconsole = None
try:
    oom_inst_oc5_interactiveconsole = callFunc("oc5_init", "InteractiveConsole",
        "`\xC2\x10\x14\xD5\xCA\x13\xEB\x1D5\"qGZ\x9C-\x02",
    )
except Exception:
    oom_inst_oc5_interactiveconsole = None

if oom_inst_oc5_interactiveconsole is not None and oom_inst_oc5_interactiveconsole is not SENTINEL_VALUE:
    # OOM sequence on InteractiveConsole: __subclasshook__
    def _oom_seq_oc5():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__subclasshook__", file=stderr)
            getattr(oom_inst_oc5_interactiveconsole, "__subclasshook__", None)(
                Template("\x00", Interpolation(weird_instances['weird_list_special'], "name")),
            )
        except BaseException:
            pass
    oom_run("oc5:code.InteractiveConsole[__subclasshook__]", _oom_seq_oc5, window=6)

    del oom_inst_oc5_interactiveconsole
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

