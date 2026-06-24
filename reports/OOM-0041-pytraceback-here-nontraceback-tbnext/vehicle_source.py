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
seed(465943586)

from string.templatelib import Interpolation, Template
print("Importing target module: inspect", file=stderr)
import inspect

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
    func_display_name = f"inspect.{method_name}()" if obj_to_call is inspect else f"{obj_to_call.__class__.__name__}.{method_name}()"
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
    return callMethod(prefix, inspect, func_name_str, *arguments, verbose=verbose)

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

fuzz_target_module = inspect

fuzzer_threads_alive = []
fuzzer_async_tasks = []


# FUSIL_BOILERPLATE_END


import sys
from random import choice, randint, random, sample
from sys import stderr, path as sys_path


print("--- Fuzzing 97 functions in inspect ---", file=stderr)
# OOM sequence: _signature_from_builtin > _check_class > getcallargs
def _oom_seq_f1():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_signature_from_builtin", file=stderr)
        getattr(fuzz_target_module, "_signature_from_builtin", None)(
            weird_classes['weird_bytes'],
            errback,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:_check_class", file=stderr)
        getattr(fuzz_target_module, "_check_class", None)(
            memoryview(b"abc\xe9\xff"),
            "\U0010FFFF",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:getcallargs", file=stderr)
        getattr(fuzz_target_module, "getcallargs", None)(
            "\U0010FFFF",
        )
    except BaseException:
        pass
oom_run("f1:inspect[_signature_from_builtin>_check_class>getcallargs]", _oom_seq_f1, window=5)

# OOM sequence: _get_code_position_from_tb > isbuiltin > formatargvalues > isasyncgenfunction > isfunction
def _oom_seq_f2():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_get_code_position_from_tb", file=stderr)
        getattr(fuzz_target_module, "_get_code_position_from_tb", None)(
            -9,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:isbuiltin", file=stderr)
        getattr(fuzz_target_module, "isbuiltin", None)(
            weird_instances['weird_float_neg_sys_maxsize'],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:formatargvalues", file=stderr)
        getattr(fuzz_target_module, "formatargvalues", None)(
            weird_classes['weird_Decimal'],
            -549.282,
            -9,
            Exception('fuzzer_generated_exception'),
            tuple[weird_classes['weird_Decimal']] | weird_classes['weird_frozenset'] | big_union,
            bytearray(b"abc\xe9\xff"),
            ['/tmp/fusil-fixtures/fusil_fixture.txt',
             "hV408mCfisIL7sVE/U3",
             liar1,
             TrickyClass,
             errback,
             b"\xFC\xB1\x5E\x08\x68\xB6\x12\xB8\xBE\x87\x70\x3E\xD4\xAF\x8D\x5C\x9B"],
            list[weird_classes['weird_set']],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:isasyncgenfunction", file=stderr)
        getattr(fuzz_target_module, "isasyncgenfunction", None)(
            r"bSffR\D.OFQnIS.MPLR.Jok.LW\b.YpK\sxMbH",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:isfunction", file=stderr)
        getattr(fuzz_target_module, "isfunction", None)(
            list[weird_classes['weird_bytes']],
        )
    except BaseException:
        pass
oom_run("f2:inspect[_get_code_position_from_tb>isbuiltin>formatargvalues>isasyncgenfunction>isfunction]", _oom_seq_f2, window=6)

# OOM sequence: getclasstree > getmodule > _finddoc > getgeneratorlocals > indentsize
def _oom_seq_f3():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:getclasstree", file=stderr)
        getattr(fuzz_target_module, "getclasstree", None)(
            r"Amozms?IeeIiO*QJv.K",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:getmodule", file=stderr)
        getattr(fuzz_target_module, "getmodule", None)(
            -2.626,
            '/tmp/fusil-fixtures/fusil_fixture.txt',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:_finddoc", file=stderr)
        getattr(fuzz_target_module, "_finddoc", None)(
            errback,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:getgeneratorlocals", file=stderr)
        getattr(fuzz_target_module, "getgeneratorlocals", None)(
            bytearray(b"test"),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:indentsize", file=stderr)
        getattr(fuzz_target_module, "indentsize", None)(
            bytearray(b"abc\xe9\xff"),
        )
    except BaseException:
        pass
oom_run("f3:inspect[getclasstree>getmodule>_finddoc>getgeneratorlocals>indentsize]", _oom_seq_f3, window=7)

# OOM sequence: _signature_from_builtin > indentsize > isgetsetdescriptor > getabsfile
def _oom_seq_f4():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_signature_from_builtin", file=stderr)
        getattr(fuzz_target_module, "_signature_from_builtin", None)(
            Exception('fuzzer_generated_exception'),
            list[weird_classes['weird_tuple']] | weird_classes['weird_frozenset'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:indentsize", file=stderr)
        getattr(fuzz_target_module, "indentsize", None)(
            -14,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:isgetsetdescriptor", file=stderr)
        getattr(fuzz_target_module, "isgetsetdescriptor", None)(
            list[weird_classes['weird_dict']],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:getabsfile", file=stderr)
        getattr(fuzz_target_module, "getabsfile", None)(
            list[weird_classes['weird_str']] | weird_classes['weird_list'] | big_union,
            -413,
        )
    except BaseException:
        pass
oom_run("f4:inspect[_signature_from_builtin>indentsize>isgetsetdescriptor>getabsfile]", _oom_seq_f4, window=3)

# OOM sequence: _missing_arguments
def _oom_seq_f5():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_missing_arguments", file=stderr)
        getattr(fuzz_target_module, "_missing_arguments", None)(
            tricky_classmethod,
            "\xD2\xE4\xAF2I\x8E>\x90",
            r"V\dSN\sg.T\d+E..fpztj.\wNS.",
            weird_instances['weird_complex_-2**31-1'],
        )
    except BaseException:
        pass
oom_run("f5:inspect[_missing_arguments]", _oom_seq_f5, window=3)

# OOM sequence: getblock > get_annotations
def _oom_seq_f6():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:getblock", file=stderr)
        getattr(fuzz_target_module, "getblock", None)(
            "\x04\xAE\x0F\xC5 |\xA1",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:get_annotations", file=stderr)
        getattr(fuzz_target_module, "get_annotations", None)(
            memoryview(b"abc\xe9\xff"),
        )
    except BaseException:
        pass
oom_run("f6:inspect[getblock>get_annotations]", _oom_seq_f6, window=6)

# OOM sequence: getmembers_static
def _oom_seq_f7():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:getmembers_static", file=stderr)
        getattr(fuzz_target_module, "getmembers_static", None)(
            "\U0010FFFF",
            r".VRvMInl+XdzQ.T.b?hmLzyj*",
        )
    except BaseException:
        pass
oom_run("f7:inspect[getmembers_static]", _oom_seq_f7, window=6)

# OOM sequence: getcomments > iscoroutine > getmembers > isgeneratorfunction > getgeneratorstate > getmro
def _oom_seq_f8():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:getcomments", file=stderr)
        getattr(fuzz_target_module, "getcomments", None)(
            dict[weird_classes['weird_deque']] | weird_classes['weird_Decimal'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:iscoroutine", file=stderr)
        getattr(fuzz_target_module, "iscoroutine", None)(
            memoryview(b"abc\xe9\xff"),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:getmembers", file=stderr)
        getattr(fuzz_target_module, "getmembers", None)(
            r".W\dsdx*A\w\WkW\BBQiJmR.P\dV.ngj\dOILJjiA",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:isgeneratorfunction", file=stderr)
        getattr(fuzz_target_module, "isgeneratorfunction", None)(
            "\x1Fb%\x8B\xE56S\x12",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:getgeneratorstate", file=stderr)
        getattr(fuzz_target_module, "getgeneratorstate", None)(
            dict[weird_classes['weird_float']],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:getmro", file=stderr)
        getattr(fuzz_target_module, "getmro", None)(
        )
    except BaseException:
        pass
oom_run("f8:inspect[getcomments>iscoroutine>getmembers>isgeneratorfunction>getgeneratorstate>getmro]", _oom_seq_f8, window=6)

# OOM sequence: _get_code_position > _get_code_position > _findclass > signature
def _oom_seq_f9():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_get_code_position", file=stderr)
        getattr(fuzz_target_module, "_get_code_position", None)(
            tricky_dict,
            '/tmp/fusil-fixtures/fusil_fixture.txt',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:_get_code_position", file=stderr)
        getattr(fuzz_target_module, "_get_code_position", None)(
            -206.98,
            "\x00",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:_findclass", file=stderr)
        getattr(fuzz_target_module, "_findclass", None)(
            "\U0010FFFF",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:signature", file=stderr)
        getattr(fuzz_target_module, "signature", None)(
            weird_classes['weird_frozenset'],
        )
    except BaseException:
        pass
oom_run("f9:inspect[_get_code_position>_get_code_position>_findclass>signature]", _oom_seq_f9, window=1)

# OOM sequence: _missing_arguments > getfile > iscode > _get_details_for_cli > getframeinfo > signature
def _oom_seq_f10():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:_missing_arguments", file=stderr)
        getattr(fuzz_target_module, "_missing_arguments", None)(
            list[weird_classes['weird_tuple']],
            None,
            -50.55,
            "A" * (2**10),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:getfile", file=stderr)
        getattr(fuzz_target_module, "getfile", None)(
            None,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:iscode", file=stderr)
        getattr(fuzz_target_module, "iscode", None)(
            memoryview(bytearray(b"abc\xe9\xff")),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s4:_get_details_for_cli", file=stderr)
        getattr(fuzz_target_module, "_get_details_for_cli", None)(
            "\x00",
            Template("\x00", Interpolation(-sys.float_info.epsilon, "value")),
            False,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s5:getframeinfo", file=stderr)
        getattr(fuzz_target_module, "getframeinfo", None)(
            b"\xB1\xB4\x6D\x50\x4B\xEC",
            b"\x67\xD3\xA2\x90\xE6\x23\x99\x6D\x7F\xB2",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s6:signature", file=stderr)
        getattr(fuzz_target_module, "signature", None)(
            ",F\xCF\xBD",
        )
    except BaseException:
        pass
oom_run("f10:inspect[_missing_arguments>getfile>iscode>_get_details_for_cli>getframeinfo>signature]", _oom_seq_f10, window=4)


print("--- OOM-fuzzing 22 classes in inspect ---", file=stderr)
# OOM sweep: FrameInfo() constructor
oom_call("oc1:inspect.FrameInfo", getattr(fuzz_target_module, "FrameInfo", None),
)

oom_inst_oc1_frameinfo = None
try:
    oom_inst_oc1_frameinfo = callFunc("oc1_init", "FrameInfo",
    )
except Exception:
    oom_inst_oc1_frameinfo = None

if oom_inst_oc1_frameinfo is not None and oom_inst_oc1_frameinfo is not SENTINEL_VALUE:
    # OOM sequence on FrameInfo: __format__ > __getnewargs__
    def _oom_seq_oc1():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__format__", file=stderr)
            getattr(oom_inst_oc1_frameinfo, "__format__", None)(
                -88310520615513,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__getnewargs__", file=stderr)
            getattr(oom_inst_oc1_frameinfo, "__getnewargs__", None)(
            )
        except BaseException:
            pass
    oom_run("oc1:inspect.FrameInfo[__format__>__getnewargs__]", _oom_seq_oc1, window=2)

    del oom_inst_oc1_frameinfo
    collect()

# OOM sweep: Arguments() constructor
oom_call("oc2:inspect.Arguments", getattr(fuzz_target_module, "Arguments", None),
)

oom_inst_oc2_arguments = None
try:
    oom_inst_oc2_arguments = callFunc("oc2_init", "Arguments",
    )
except Exception:
    oom_inst_oc2_arguments = None

if oom_inst_oc2_arguments is not None and oom_inst_oc2_arguments is not SENTINEL_VALUE:
    # OOM sequence on Arguments: __gt__
    def _oom_seq_oc2():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__gt__", file=stderr)
            getattr(oom_inst_oc2_arguments, "__gt__", None)(
                bytearray(b"abc\xe9\xff"),
            )
        except BaseException:
            pass
    oom_run("oc2:inspect.Arguments[__gt__]", _oom_seq_oc2, window=6)

    del oom_inst_oc2_arguments
    collect()

# OOM sweep: _FrameInfo() constructor
oom_call("oc3:inspect._FrameInfo", getattr(fuzz_target_module, "_FrameInfo", None),
)

oom_inst_oc3__frameinfo = None
try:
    oom_inst_oc3__frameinfo = callFunc("oc3_init", "_FrameInfo",
    )
except Exception:
    oom_inst_oc3__frameinfo = None

if oom_inst_oc3__frameinfo is not None and oom_inst_oc3__frameinfo is not SENTINEL_VALUE:
    # OOM sequence on _FrameInfo: __replace__ > __init_subclass__ > __iter__ > __init_subclass__
    def _oom_seq_oc3():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__replace__", file=stderr)
            getattr(oom_inst_oc3__frameinfo, "__replace__", None)(
                memoryview(bytearray(b"abc\xe9\xff")),
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__init_subclass__", file=stderr)
            getattr(oom_inst_oc3__frameinfo, "__init_subclass__", None)(
                "K7AcnTmPTMgks.hTPc.5mCqoY6Qkhv8Etp0-_b07BacTo1j9.6FKo/../hxN/-Ryg",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__iter__", file=stderr)
            getattr(oom_inst_oc3__frameinfo, "__iter__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__init_subclass__", file=stderr)
            getattr(oom_inst_oc3__frameinfo, "__init_subclass__", None)(
                tricky_module,
            )
        except BaseException:
            pass
    oom_run("oc3:inspect._FrameInfo[__replace__>__init_subclass__>__iter__>__init_subclass__]", _oom_seq_oc3, window=3)

    del oom_inst_oc3__frameinfo
    collect()

# OOM sweep: BlockFinder() constructor
oom_call("oc4:inspect.BlockFinder", getattr(fuzz_target_module, "BlockFinder", None),
)

oom_inst_oc4_blockfinder = None
try:
    oom_inst_oc4_blockfinder = callFunc("oc4_init", "BlockFinder",
    )
except Exception:
    oom_inst_oc4_blockfinder = None

if oom_inst_oc4_blockfinder is not None and oom_inst_oc4_blockfinder is not SENTINEL_VALUE:
    # OOM sequence on BlockFinder: __getstate__ > __ge__ > tokeneater > __new__ > __subclasshook__
    def _oom_seq_oc4():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__getstate__", file=stderr)
            getattr(oom_inst_oc4_blockfinder, "__getstate__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__ge__", file=stderr)
            getattr(oom_inst_oc4_blockfinder, "__ge__", None)(
                bytes(range(256)),
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:tokeneater", file=stderr)
            getattr(oom_inst_oc4_blockfinder, "tokeneater", None)(
                bytearray(b"A" * 2**10),
                "\xFA\x1E\xFA;",
                -9.6280,
                "/j77TV-a8_w1NY-kLK0G/../YlqFaRr0t.G/g/c6T7/./iI/F",
                {b"\x74\xB2\x57\xB7\xD8\x0D\x05\xDE\x23\x7D\xA3\x24\x13\xDD": Exception('fuzzer_generated_exception'),
                 "\x91^\xAD": "\udbff\udfff",
                 "t\xF5": None,
                 "\u122F\uD445\uB943\uFB56\u8ACF\uE38B\u9179\u23D2\u655F\u5750\uF7D7\u41E1\uFAE5": MagicMock(),
                 '/tmp/fusil-fixtures/fusil_fixture.bin': sys.float_info.min,
                 -3: r"\d{1,100}"},
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__new__", file=stderr)
            getattr(oom_inst_oc4_blockfinder, "__new__", None)(
                b"\xD9\xB1\x5A",
                "\u71A6\u8824\uBB19\u5A67\u9A27\u94F3\u5050\uEFC2\uD1FA\u3479\uC8E1\uA1DF\uC72F\uC841\u8A91\uDE23",
                14.34,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:__subclasshook__", file=stderr)
            getattr(oom_inst_oc4_blockfinder, "__subclasshook__", None)(
                Exception('fuzzer_generated_exception'),
            )
        except BaseException:
            pass
    oom_run("oc4:inspect.BlockFinder[__getstate__>__ge__>tokeneater>__new__>__subclasshook__]", _oom_seq_oc4, window=4)

    del oom_inst_oc4_blockfinder
    collect()

# OOM sweep: _empty() constructor
oom_call("oc5:inspect._empty", getattr(fuzz_target_module, "_empty", None),
)

oom_inst_oc5__empty = None
try:
    oom_inst_oc5__empty = callFunc("oc5_init", "_empty",
    )
except Exception:
    oom_inst_oc5__empty = None

if oom_inst_oc5__empty is not None and oom_inst_oc5__empty is not SENTINEL_VALUE:
    # OOM sequence on _empty: __eq__ > __init__ > __init__ > __getstate__ > __format__
    def _oom_seq_oc5():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__eq__", file=stderr)
            getattr(oom_inst_oc5__empty, "__eq__", None)(
                list[weird_classes['weird_bytearray']],
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__init__", file=stderr)
            getattr(oom_inst_oc5__empty, "__init__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__init__", file=stderr)
            getattr(oom_inst_oc5__empty, "__init__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m4:__getstate__", file=stderr)
            getattr(oom_inst_oc5__empty, "__getstate__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m5:__format__", file=stderr)
            getattr(oom_inst_oc5__empty, "__format__", None)(
                tricky_property,
            )
        except BaseException:
            pass
    oom_run("oc5:inspect._empty[__eq__>__init__>__init__>__getstate__>__format__]", _oom_seq_oc5, window=4)

    del oom_inst_oc5__empty
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

