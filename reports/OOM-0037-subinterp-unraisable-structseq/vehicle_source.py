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
seed(715387518)

from string.templatelib import Interpolation, Template
print("Importing target module: concurrent.futures.interpreter", file=stderr)
import concurrent.futures.interpreter

TRIVIAL_TYPES = {int, str, float, bool, bytes, tuple, list, dict, set, type(None),}
def skip_trivial_type(obj_instance_or_class):
    if type(obj_instance_or_class) in TRIVIAL_TYPES:
        return True
    return False


import faulthandler
faulthandler.enable()
try:
    from _testcapi import set_nomemory as _set_nomemory, remove_mem_hooks as _remove_mem_hooks
    _OOM_AVAILABLE = True
except ImportError:
    _OOM_AVAILABLE = False
    print("OOM mode requested but _testcapi.set_nomemory unavailable; running without injection", file=stderr)

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

tricky_strs = (chr(0), chr(127), chr(255), chr(0x10FFFF), "𝒜","\\x00" * 10, "A" * (2 ** 16), "💻" * 2**10,)

# We cannot create a Decimal larger than 10 ** 4300 with _pydecimal, only with _decimal
max_str_digits_adjustment = 1 if has__decimal else -1
big_int_for_decimal = 10 ** (sys.int_info.default_max_str_digits + max_str_digits_adjustment)

for cls in sequences:
    weird_instances[f"weird_{cls.__name__}_single"] = weird_classes[f"weird_{cls.__name__}"]("a")
    weird_instances[f"weird_{cls.__name__}_range"] = weird_classes[f"weird_{cls.__name__}"](range(20))
    weird_instances[f"weird_{cls.__name__}_types"] = weird_classes[f"weird_{cls.__name__}"](bases)
    weird_instances[f"weird_{cls.__name__}_printable"] = weird_classes[f"weird_{cls.__name__}"](printable)
    weird_instances[f"weird_{cls.__name__}_special"] = weird_classes[f"weird_{cls.__name__}"](tricky_strs)
for cls in bytes_:
    weird_instances[f"weird_{cls.__name__}_bytes"] = weird_classes[f"weird_{cls.__name__}"](b"abcdefgh_" * 10)
for cls in numbers:
    weird_instances[f"weird_{cls.__name__}_sys_maxsize"] = weird_classes[f"weird_{cls.__name__}"](sys.maxsize)
    weird_instances[f"weird_{cls.__name__}_sys_maxsize_minus_one"] = weird_classes[f"weird_{cls.__name__}"](sys.maxsize - 1)
    weird_instances[f"weird_{cls.__name__}_sys_maxsize_plus_one"] = weird_classes[f"weird_{cls.__name__}"](sys.maxsize + 1)
    weird_instances[f"weird_{cls.__name__}_neg_sys_maxsize"] = weird_classes[f"weird_{cls.__name__}"](-sys.maxsize)
    weird_instances[f"weird_{cls.__name__}_2**63-1"] = weird_classes[f"weird_{cls.__name__}"](2 ** 63 - 1)
    weird_instances[f"weird_{cls.__name__}_2**63"] = weird_classes[f"weird_{cls.__name__}"](2 ** 63)
    weird_instances[f"weird_{cls.__name__}_2**63+1"] = weird_classes[f"weird_{cls.__name__}"](2 ** 63 + 1)
    weird_instances[f"weird_{cls.__name__}_-2**63+1"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 63 + 1)
    weird_instances[f"weird_{cls.__name__}_-2**63"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 63)
    weird_instances[f"weird_{cls.__name__}_-2**63-1"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 63 -1)
    weird_instances[f"weird_{cls.__name__}_2**31-1"] = weird_classes[f"weird_{cls.__name__}"](2 ** 31 - 1)
    weird_instances[f"weird_{cls.__name__}_2**31"] = weird_classes[f"weird_{cls.__name__}"](2 ** 31)
    weird_instances[f"weird_{cls.__name__}_2**31+1"] = weird_classes[f"weird_{cls.__name__}"](2 ** 31 + 1)
    weird_instances[f"weird_{cls.__name__}_-2**31+1"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 31 + 1)
    weird_instances[f"weird_{cls.__name__}_-2**31"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 31)
    weird_instances[f"weird_{cls.__name__}_-2**31-1"] = weird_classes[f"weird_{cls.__name__}"](-2 ** 31 - 1)
    if cls not in (float, complex) and hasattr(sys, 'int_info'):
        weird_instances[f"weird_{cls.__name__}_10**default_max_str_digits+1"] = weird_classes[f"weird_{cls.__name__}"](big_int_for_decimal)
for cls in dicts:
    weird_instances[f"weird_{cls.__name__}_basic"] = weird_classes[f"weird_{cls.__name__}"]({a: a for a in range(100)})
    weird_instances[f"weird_{cls.__name__}_tricky_strs"] = weird_classes[f"weird_{cls.__name__}"]({a: a for a in tricky_strs})


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
            print(f"  [Side Effect] In __del__: Modifying '{self.var_name}' to {self.new_value!r}", file=sys.stderr)
            if self.var_name in frame.f_locals:
                frame.f_locals[self.var_name] = self.new_value
            elif self.var_name.split(".")[0] in frame.f_locals and self.var_name.count(".") == 1:  # instance_or_class.attribute
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

all_types = (abc_types + builtins_types + collections_abc_types + collections_types + itertools_types
             + types_types + typing_types)
all_types = [t for t in all_types if not (isinstance(t, type) and issubclass(t, BaseException))]
big_union = reduce(or_, all_types, int)


import types
import inspect
import itertools
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
if tricky_capsule: tricky_dict[tricky_capsule] = tricky_cell
if tricky_module: tricky_dict[tricky_module] = tricky_genericalias
tricky_dict["tricky_dict"] = tricky_dict
tricky_mappingproxy = types.MappingProxyType(tricky_dict)


def tricky_function(*args, **kwargs):
    if len(args) > 150: raise RecursionError("Fuzzer controlled depth")
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
tricky_classmethod_descriptor = types.ClassMethodDescriptorType # This is the type itself


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
        #return super().__mro_entries__(bases)


class TrickyClass(metaclass=TrickyMeta):
    tricky_descriptor = TrickyDescriptor()

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        self._value_init = None

    def __getattr__(self, name):
        if name == "crash_on_getattr": raise ValueError("getattr manipulated")
        return self


tricky_instance = TrickyClass()
try:
    tricky_frame = inspect.currentframe()
    if tricky_frame: # currentframe() can be None
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
    func_display_name = f"concurrent.futures.interpreter.{method_name}()" if obj_to_call is concurrent.futures.interpreter else f"{obj_to_call.__class__.__name__}.{method_name}()"
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
    return callMethod(prefix, concurrent.futures.interpreter, func_name_str, *arguments, verbose=verbose)

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
    # remove_mem_hooks runs in the inner finally so the except clauses
    # allocate with the allocator restored.
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
                _remove_mem_hooks()
        except MemoryError:
            pass
        except SystemError:
            print("[OOM] SystemError in " + label, file=stderr)
        except BaseException:
            pass

_OOM_WINDOW = 5

def oom_run(label, thunk):
    # Stateful OOM sequence (Phase 4): sweep a bounded failure window
    # across a multi-step thunk so a failure in one step can corrupt
    # state a later step trips over. set_nomemory(start, start+_OOM_WINDOW)
    # fails _OOM_WINDOW allocations then resumes succeeding, so steps after
    # the burst run on the damaged state (_OOM_WINDOW == 0 -> fail forever,
    # the legacy single-call semantics). The thunk guards each step
    # internally so the tail still runs after an earlier step raises; a real
    # crash (segfault/abort) terminates the process and is scored.
    if not _OOM_AVAILABLE:
        try:
            thunk()
        except BaseException:
            pass
        return
    print("[OOM-SEQ] " + label, file=stderr)
    for _start in range(_OOM_MAX_START):
        if _OOM_VERBOSE:
            print("[OOM-SEQ]   start=" + str(_start) + " window=" + str(_OOM_WINDOW), file=stderr)
        if _OOM_WINDOW > 0:
            _set_nomemory(_start, _start + _OOM_WINDOW)
        else:
            _set_nomemory(_start, 0)
        try:
            try:
                thunk()
            finally:
                _remove_mem_hooks()
        except MemoryError:
            pass
        except SystemError:
            print("[OOM-SEQ] SystemError in " + label, file=stderr)
        except BaseException:
            pass

fuzz_target_module = concurrent.futures.interpreter

fuzzer_threads_alive = []
fuzzer_async_tasks = []


# FUSIL_BOILERPLATE_END


import sys
from random import choice, randint, random, sample
from sys import stderr, path as sys_path


print("--- Fuzzing 1 functions in concurrent.futures.interpreter ---", file=stderr)
# OOM sequence: do_call > do_call > do_call
def _oom_seq_f1():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            "\x00",
            liar1,
            202.6,
            None,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            "\x00",
            complex(-10 ** 10, 10 ** 10),
            r"bYA\SMcetR*IT.vG.yEmZ\BCgiV\Zu",
            sys.float_info.min,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            [],
            r"auEI.w\biKoIKM?ljO*H",
            "\x07\x1F\xAA\xD8,~>\xC9\xAA\xF0@Z{",
            "\uFF6E\uB604\u9806\u732B",
        )
    except BaseException:
        pass
oom_run("f1:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f1)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f2():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            tricky_staticmethod,
            "\x87\xF3\xF9\x17\xBBK\x10\xA9\xA3]\x88r\xB3",
            None,
            -1756019538732628,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            b"\xFC\xF6\x87\xC0\x03\x61\xDD\xD3",
            "\uF406\u1C48\u6406\u1141\u1EAF\u15D1\uB781\uBEBA\uA3FB\uF470\uDF2A\uF700\uE8ED\u1412\u40E5\uBB42",
            None,
            r"H.iW.ZJh\B.MF.\smSDW.\Z*qC\sqlgasKWWq*.TM",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            ":\x8E\x90\xE0",
            "\U0010FFFF",
            weird_classes['weird_frozenset'],
            Evil(),
        )
    except BaseException:
        pass
oom_run("f2:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f2)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f3():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            tuple[weird_classes['weird_Queue']],
            '/etc/machine-id',
            "Nl\xBB\xD9\xD4\xB5\x1E\xB6\xDF",
            True,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            float("0.0000001"),
            weird_instances['weird_str_empty'],
            weird_instances['weird_tuple_types'],
            "\u2BDF\u2F77\uD64B\u150B\u19F8\u71E7\u1CCB\u30DD\uD637\uFE18\uCBC1\u2280",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            TrickyMeta,
            '/bin/sh',
            r"jlQKka..aoVMEL\BR",
            "OwWqAC_8v7Sg6ROeqZN01rPN4-WH-ruBqG48icEe3yIg9FA520ZzKmcz7xBrB69fk-f5ZH__Zks0o/QbZ5thMF56/Ei",
        )
    except BaseException:
        pass
oom_run("f3:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f3)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f4():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            tricky_traceback,
            float("-inf"),
            tuple[weird_classes['weird_Decimal']] | weird_classes['weird_dict'] | big_union,
            -622150017804,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            b"\xE5\xE1\x18\xF4\x85\x61\xA3\x06\x16\x8E\xBF\xBC\x22\x0F\xB5",
            [],
            Exception('fuzzer_generated_exception'),
            '/etc/machine-id',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            (errback,
             "e\x94v\xFAZ3\"\xAAC",
             True,
             Exception('fuzzer_generated_exception'),
             "\u2F25\u017B\uD43F\uD666\u7100\u20F8\uBC90\u0B9B\u7BE4\u0B15\u353D\u37AB",
             None,
             Exception('fuzzer_generated_exception'),
             r"nN.e*fHQL.\DfIW\Df.i\WwaNXmAO+."),
            tuple[weird_classes['weird_Decimal']] | weird_classes['weird_int'] | big_union,
            (lambda x: sys.maxsize),
            Template("\x00", Interpolation(weird_instances['weird_int_sys_maxsize'], "name")),
        )
    except BaseException:
        pass
oom_run("f4:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f4)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f5():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            bytes(range(256)),
            b"\xED\x06\xBA\xDA",
            weird_instances['weird_OrderedDict_basic'],
            bytearray(b"A" * 2**10),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            b"\xE9",
            r"\A[\w-]+\Z",
            r"g.RAb\Z\AYdVlF\BKneoLVhWCo\wN",
            Exception('fuzzer_generated_exception'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            list[weird_classes['weird_set']] | weird_classes['weird_bytes'] | big_union,
            "\xB2\xBC )\\\xA9S",
            -918.9653,
            weird_classes['weird_bytes'],
        )
    except BaseException:
        pass
oom_run("f5:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f5)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f6():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            -18,
            3,
            tuple[weird_classes['weird_bytearray']] | weird_classes['weird_bytes'] | big_union,
            tuple[weird_classes['weird_complex']],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            bytearray(b"abc\xe9\xff"),
            errback,
            Template("\x00", Interpolation(weird_instances['weird_frozenset_single'], "name")),
            "\u4775\uD321\u2A21\u593B\u27C6\u9618\u5891\uBBD0",
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            [261,
             11,
             dict[weird_classes['weird_complex']] | weird_classes['weird_bytes'] | big_union,
             None],
            b"\x11\xA0\x76",
            tuple[weird_classes['weird_frozenset']],
            '/etc/machine-id',
        )
    except BaseException:
        pass
oom_run("f6:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f6)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f7():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            None,
            "/.gjE/./PsM32oFv//6apQXDWtiXnBawKzP4TViiZx8a4yow/../bGbLLO0mvqz5fZm-tJs_3xTr5aJdKk7/Y2S8m1q",
            '/bin/sh',
            tricky_instance,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            "qYhuXwSDUFaV8vnvV_-J/ybR3FN//Vsy/s",
            TrickyClass,
            memoryview(b"abc\xe9\xff"),
            '/bin/sh',
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            "\uDC80",
            int,
            "/HcmkCCczfpnjGM.0jWkyWBNNy4k_XK3260SDp40Txnw0tsXUByriTE5EzPypzn0A0M/zVyC2/d/.BNrtual/t/",
            "3(",
        )
    except BaseException:
        pass
oom_run("f7:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f7)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f8():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            None,
            weird_classes['weird_object'],
            None,
            tuple[weird_classes['weird_Queue']] | weird_classes['weird_Counter'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            weird_instances['weird_complex_empty'],
            "𝒜",
            True,
            weird_classes['weird_Queue'],
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            '/etc/machine-id',
            -684431853671556217,
            list[weird_classes['weird_str']],
            None,
        )
    except BaseException:
        pass
oom_run("f8:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f8)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f9():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            list[weird_classes['weird_float']] | weird_classes['weird_Decimal'] | big_union,
            True,
            memoryview(b"abc\xe9\xff"),
            {"\uD9EB\uFFB9\uC6BA\uD59E\uFB91\u4C22\uF863\u74B0\uB114\u6948\u36DA\uA5E7\u5A7D\uEF57\u5D06\u7515\u500F\u0971",
             False,
             -8,
             -48.612,
             "\x01\x0El",
             errback,
             "\x0B\xF2]\xE1",
             Exception('fuzzer_generated_exception'),
             Exception('fuzzer_generated_exception')},
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            8256691076616717218,
            memoryview(b"abc\xe9\xff"),
            chr(127),
            Exception('fuzzer_generated_exception'),
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            bytes(10 ** 5),
            "\x9E9v\x06\xD4\x8DZ",
            "\x00",
            dict[weird_classes['weird_Counter']] | weird_classes['weird_set'] | big_union,
        )
    except BaseException:
        pass
oom_run("f9:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f9)

# OOM sequence: do_call > do_call > do_call
def _oom_seq_f10():
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s1:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            dict[weird_classes['weird_bytearray']],
            tricky_staticmethod,
            None,
            int,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s2:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            weird_classes['weird_deque'],
            r"..Kj.d\WmDd.\BjOAIUT",
            13,
            list[weird_classes['weird_object']] | weird_classes['weird_list'] | big_union,
        )
    except BaseException:
        pass
    try:
        if _OOM_VERBOSE:
            print("[OOM-SEQ]     step s3:do_call", file=stderr)
        getattr(fuzz_target_module, "do_call", None)(
            set(),
            list[weird_classes['weird_float']] | weird_classes['weird_Queue'] | big_union,
            errback,
            list[weird_classes['weird_set']] | weird_classes['weird_Queue'] | big_union,
        )
    except BaseException:
        pass
oom_run("f10:concurrent.futures.interpreter[do_call>do_call>do_call]", _oom_seq_f10)


print("--- OOM-fuzzing 2 classes in concurrent.futures.interpreter ---", file=stderr)
# OOM sweep: InterpreterPoolExecutor() constructor
oom_call("oc1:concurrent.futures.interpreter.InterpreterPoolExecutor", getattr(fuzz_target_module, "InterpreterPoolExecutor", None),
)

oom_inst_oc1_interpreterpoolexecutor = None
try:
    oom_inst_oc1_interpreterpoolexecutor = callFunc("oc1_init", "InterpreterPoolExecutor",
    )
except Exception:
    oom_inst_oc1_interpreterpoolexecutor = None

if oom_inst_oc1_interpreterpoolexecutor is not None and oom_inst_oc1_interpreterpoolexecutor is not SENTINEL_VALUE:
    # OOM sequence on InterpreterPoolExecutor: __lt__ > __init__ > submit
    def _oom_seq_oc1():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__lt__", file=stderr)
            getattr(oom_inst_oc1_interpreterpoolexecutor, "__lt__", None)(
                "\uBA9B\uD92B\u4949\u637C\u490C\uDB5D\u93DC\u5ECE\u9475\u393B\u0D55\u267C\uF2CB",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__init__", file=stderr)
            getattr(oom_inst_oc1_interpreterpoolexecutor, "__init__", None)(
                Exception('fuzzer_generated_exception'),
                list[weird_classes['weird_Decimal']] | weird_classes['weird_int'] | big_union,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:submit", file=stderr)
            getattr(oom_inst_oc1_interpreterpoolexecutor, "submit", None)(
                681872975,
            )
        except BaseException:
            pass
    oom_run("oc1:concurrent.futures.interpreter.InterpreterPoolExecutor[__lt__>__init__>submit]", _oom_seq_oc1)

    del oom_inst_oc1_interpreterpoolexecutor
    collect()

# OOM sweep: WorkerContext() constructor
oom_call("oc2:concurrent.futures.interpreter.WorkerContext", getattr(fuzz_target_module, "WorkerContext", None),
    Evil(),
)

oom_inst_oc2_workercontext = None
try:
    oom_inst_oc2_workercontext = callFunc("oc2_init", "WorkerContext",
        "2nt5SB9YQCz_j4zxT4a7KV3xix.9t/G_k",
    )
except Exception:
    oom_inst_oc2_workercontext = None

if oom_inst_oc2_workercontext is not None and oom_inst_oc2_workercontext is not SENTINEL_VALUE:
    # OOM sequence on WorkerContext: __repr__ > finalize > __eq__
    def _oom_seq_oc2():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__repr__", file=stderr)
            getattr(oom_inst_oc2_workercontext, "__repr__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:finalize", file=stderr)
            getattr(oom_inst_oc2_workercontext, "finalize", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__eq__", file=stderr)
            getattr(oom_inst_oc2_workercontext, "__eq__", None)(
                9.482,
            )
        except BaseException:
            pass
    oom_run("oc2:concurrent.futures.interpreter.WorkerContext[__repr__>finalize>__eq__]", _oom_seq_oc2)

    del oom_inst_oc2_workercontext
    collect()

# OOM sweep: InterpreterPoolExecutor() constructor
oom_call("oc3:concurrent.futures.interpreter.InterpreterPoolExecutor", getattr(fuzz_target_module, "InterpreterPoolExecutor", None),
    "\xCCy\xEF",
    r"X?\wFZq\S.\bhdx\w.T.cJE\Sf",
    {r"FTcda?\W.VUd\B..g.Dv\W.n": b"\x0A\x68\xAD\x33\xAC",
     b"\x52\x0E\x73\x5A\x62\x4E\xCD\x7E\xDE\xBD": None,
     "\U0010FFFF": '/bin/sh',
     None: dict[weird_classes['weird_tuple']] | weird_classes['weird_bytes'] | big_union,
     r"X\DgCVTT\wCLqQLlr": Evil,
     b"\xAB\x8B\xE0\x74\xE6\x5F\x41\x85\x97\x37\x52\x8A\x73\x0A\x64": tuple[weird_classes['weird_set']] | weird_classes['weird_int'] | big_union,
     "\uDC80": b""},
    r"HXwwd..D+\bd?LF.HXSk\bE\sYcU?",
)

oom_inst_oc3_interpreterpoolexecutor = None
try:
    oom_inst_oc3_interpreterpoolexecutor = callFunc("oc3_init", "InterpreterPoolExecutor",
        b"\x4F\xA0\x72\xDE\xFC\x67\x9F\x5E\x04\x66\x25\x4A",
        True,
        r".\WQBq.XqP\A\A+IUS",
        tuple[weird_classes['weird_tuple']] | weird_classes['weird_complex'] | big_union,
    )
except Exception:
    oom_inst_oc3_interpreterpoolexecutor = None

if oom_inst_oc3_interpreterpoolexecutor is not None and oom_inst_oc3_interpreterpoolexecutor is not SENTINEL_VALUE:
    # OOM sequence on InterpreterPoolExecutor: __delattr__ > __str__ > __new__
    def _oom_seq_oc3():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__delattr__", file=stderr)
            getattr(oom_inst_oc3_interpreterpoolexecutor, "__delattr__", None)(
                -11,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__str__", file=stderr)
            getattr(oom_inst_oc3_interpreterpoolexecutor, "__str__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__new__", file=stderr)
            getattr(oom_inst_oc3_interpreterpoolexecutor, "__new__", None)(
                r"EPrdRny.R.q.lOZ.dkmwe.\Z",
                -5370,
                list[weird_classes['weird_int']],
            )
        except BaseException:
            pass
    oom_run("oc3:concurrent.futures.interpreter.InterpreterPoolExecutor[__delattr__>__str__>__new__]", _oom_seq_oc3)

    del oom_inst_oc3_interpreterpoolexecutor
    collect()

# OOM sweep: InterpreterPoolExecutor() constructor
oom_call("oc4:concurrent.futures.interpreter.InterpreterPoolExecutor", getattr(fuzz_target_module, "InterpreterPoolExecutor", None),
    '/etc/machine-id',
    list[weird_classes['weird_Decimal']],
    (Exception('fuzzer_generated_exception'),
     '/bin/sh',
     list[weird_classes['weird_dict']] | weird_classes['weird_object'] | big_union,
     weird_classes['weird_dict'],
     Liar1),
    "]Zi\xCA\x9B@\x88&",
)

oom_inst_oc4_interpreterpoolexecutor = None
try:
    oom_inst_oc4_interpreterpoolexecutor = callFunc("oc4_init", "InterpreterPoolExecutor",
        "\x10[?\xB4b~",
        tuple[weird_classes['weird_Queue']],
        weird_classes['weird_list'],
        823.305,
    )
except Exception:
    oom_inst_oc4_interpreterpoolexecutor = None

if oom_inst_oc4_interpreterpoolexecutor is not None and oom_inst_oc4_interpreterpoolexecutor is not SENTINEL_VALUE:
    # OOM sequence on InterpreterPoolExecutor: __hash__ > __str__ > __new__
    def _oom_seq_oc4():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:__hash__", file=stderr)
            getattr(oom_inst_oc4_interpreterpoolexecutor, "__hash__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__str__", file=stderr)
            getattr(oom_inst_oc4_interpreterpoolexecutor, "__str__", None)(
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__new__", file=stderr)
            getattr(oom_inst_oc4_interpreterpoolexecutor, "__new__", None)(
                bytearray(b"abc\xe9\xff"),
                b"\x46\x08",
                9.4,
            )
        except BaseException:
            pass
    oom_run("oc4:concurrent.futures.interpreter.InterpreterPoolExecutor[__hash__>__str__>__new__]", _oom_seq_oc4)

    del oom_inst_oc4_interpreterpoolexecutor
    collect()

# OOM sweep: InterpreterPoolExecutor() constructor
oom_call("oc5:concurrent.futures.interpreter.InterpreterPoolExecutor", getattr(fuzz_target_module, "InterpreterPoolExecutor", None),
)

oom_inst_oc5_interpreterpoolexecutor = None
try:
    oom_inst_oc5_interpreterpoolexecutor = callFunc("oc5_init", "InterpreterPoolExecutor",
    )
except Exception:
    oom_inst_oc5_interpreterpoolexecutor = None

if oom_inst_oc5_interpreterpoolexecutor is not None and oom_inst_oc5_interpreterpoolexecutor is not SENTINEL_VALUE:
    # OOM sequence on InterpreterPoolExecutor: map > __format__ > __ne__
    def _oom_seq_oc5():
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m1:map", file=stderr)
            getattr(oom_inst_oc5_interpreterpoolexecutor, "map", None)(
                tuple[weird_classes['weird_bytearray']] | weird_classes['weird_frozenset'] | big_union,
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m2:__format__", file=stderr)
            getattr(oom_inst_oc5_interpreterpoolexecutor, "__format__", None)(
                "ag\xF5\xE5\x8B\x1F\xE8\xE1j\x88\x8B:",
            )
        except BaseException:
            pass
        try:
            if _OOM_VERBOSE:
                print("[OOM-SEQ]     step m3:__ne__", file=stderr)
            getattr(oom_inst_oc5_interpreterpoolexecutor, "__ne__", None)(
                weird_classes['weird_Decimal'],
            )
        except BaseException:
            pass
    oom_run("oc5:concurrent.futures.interpreter.InterpreterPoolExecutor[map>__format__>__ne__]", _oom_seq_oc5)

    del oom_inst_oc5_interpreterpoolexecutor
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

