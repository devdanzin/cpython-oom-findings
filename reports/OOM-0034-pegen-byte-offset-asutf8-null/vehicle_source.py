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
seed(906384555)

from string.templatelib import Interpolation, Template
print("Importing target module: _pyrepl._module_completer", file=stderr)
import _pyrepl._module_completer

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
    func_display_name = f"_pyrepl._module_completer.{method_name}()" if obj_to_call is _pyrepl._module_completer else f"{obj_to_call.__class__.__name__}.{method_name}()"
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
    return callMethod(prefix, _pyrepl._module_completer, func_name_str, *arguments, verbose=verbose)

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

fuzz_target_module = _pyrepl._module_completer

fuzzer_threads_alive = []
fuzzer_async_tasks = []


# FUSIL_BOILERPLATE_END


import sys
from random import choice, randint, random, sample
from sys import stderr, path as sys_path


print("--- Fuzzing 4 functions in _pyrepl._module_completer ---", file=stderr)
# OOM sweep: dataclass
oom_call("f1:_pyrepl._module_completer.dataclass", getattr(fuzz_target_module, "dataclass"),
)

# OOM sweep: make_default_module_completer
oom_call("f2:_pyrepl._module_completer.make_default_module_completer", getattr(fuzz_target_module, "make_default_module_completer"),
)

# OOM sweep: safe_getattr
oom_call("f3:_pyrepl._module_completer.safe_getattr", getattr(fuzz_target_module, "safe_getattr"),
    weird_classes['weird_int'],
    bytearray(b"abc\xe9\xff"),
)

# OOM sweep: make_default_module_completer
oom_call("f4:_pyrepl._module_completer.make_default_module_completer", getattr(fuzz_target_module, "make_default_module_completer"),
)

# OOM sweep: make_default_module_completer
oom_call("f5:_pyrepl._module_completer.make_default_module_completer", getattr(fuzz_target_module, "make_default_module_completer"),
)

# OOM sweep: make_default_module_completer
oom_call("f6:_pyrepl._module_completer.make_default_module_completer", getattr(fuzz_target_module, "make_default_module_completer"),
)

# OOM sweep: dataclass
oom_call("f7:_pyrepl._module_completer.dataclass", getattr(fuzz_target_module, "dataclass"),
)

# OOM sweep: safe_getattr
oom_call("f8:_pyrepl._module_completer.safe_getattr", getattr(fuzz_target_module, "safe_getattr"),
    -44.998,
    "\x85r\xEE\xDC9d",
)

# OOM sweep: contextmanager
oom_call("f9:_pyrepl._module_completer.contextmanager", getattr(fuzz_target_module, "contextmanager"),
    weird_classes['weird_float'],
)

# OOM sweep: safe_getattr
oom_call("f10:_pyrepl._module_completer.safe_getattr", getattr(fuzz_target_module, "safe_getattr"),
    weird_classes['weird_tuple'],
    b"\x3B\xB6\x63\xD7\x94",
)


print("--- OOM-fuzzing 8 classes in _pyrepl._module_completer ---", file=stderr)
# OOM sweep: ModuleCompleter() constructor
oom_call("oc1:_pyrepl._module_completer.ModuleCompleter", getattr(fuzz_target_module, "ModuleCompleter", None),
    weird_instances['weird_Counter_tricky_strs'],
)

oom_inst_oc1_modulecompleter = None
try:
    oom_inst_oc1_modulecompleter = callFunc("oc1_init", "ModuleCompleter",
        15,
    )
except Exception:
    oom_inst_oc1_modulecompleter = None

if oom_inst_oc1_modulecompleter is not None and oom_inst_oc1_modulecompleter is not SENTINEL_VALUE:
    # OOM sweep: ModuleCompleter._get_import_completion_action()
    oom_call("oc1m1:_pyrepl._module_completer.ModuleCompleter._get_import_completion_action", getattr(oom_inst_oc1_modulecompleter, "_get_import_completion_action", None),
        '/bin/sh',
    )
    # OOM sweep: ModuleCompleter.format_completion()
    oom_call("oc1m2:_pyrepl._module_completer.ModuleCompleter.format_completion", getattr(oom_inst_oc1_modulecompleter, "format_completion", None),
        "\x00",
        "../Z9WZAb/../eG/",
    )
    # OOM sweep: ModuleCompleter.__subclasshook__()
    oom_call("oc1m3:_pyrepl._module_completer.ModuleCompleter.__subclasshook__", getattr(oom_inst_oc1_modulecompleter, "__subclasshook__", None),
        -477293,
    )
    # OOM sweep: ModuleCompleter.__le__()
    oom_call("oc1m4:_pyrepl._module_completer.ModuleCompleter.__le__", getattr(oom_inst_oc1_modulecompleter, "__le__", None),
        chr(127),
    )
    # OOM sweep: ModuleCompleter._resolve_relative_path()
    oom_call("oc1m5:_pyrepl._module_completer.ModuleCompleter._resolve_relative_path", getattr(oom_inst_oc1_modulecompleter, "_resolve_relative_path", None),
        '/bin/sh',
    )
    del oom_inst_oc1_modulecompleter
    collect()

# OOM sweep: TokenQueue() constructor
oom_call("oc2:_pyrepl._module_completer.TokenQueue", getattr(fuzz_target_module, "TokenQueue", None),
    weird_classes['weird_bytearray'],
)

oom_inst_oc2_tokenqueue = None
try:
    oom_inst_oc2_tokenqueue = callFunc("oc2_init", "TokenQueue",
        -2 ** 63,
    )
except Exception:
    oom_inst_oc2_tokenqueue = None

if oom_inst_oc2_tokenqueue is not None and oom_inst_oc2_tokenqueue is not SENTINEL_VALUE:
    # OOM sweep: TokenQueue.pop()
    oom_call("oc2m1:_pyrepl._module_completer.TokenQueue.pop", getattr(oom_inst_oc2_tokenqueue, "pop", None),
        list[weird_classes['weird_str']],
    )
    # OOM sweep: TokenQueue.__ge__()
    oom_call("oc2m2:_pyrepl._module_completer.TokenQueue.__ge__", getattr(oom_inst_oc2_tokenqueue, "__ge__", None),
        dict[weird_classes['weird_Queue']],
    )
    # OOM sweep: TokenQueue.__new__()
    oom_call("oc2m3:_pyrepl._module_completer.TokenQueue.__new__", getattr(oom_inst_oc2_tokenqueue, "__new__", None),
        "\x1C\xF2\xE1v\xF34f\xD2",
        tricky_genericalias,
        '/etc/machine-id',
    )
    # OOM sweep: TokenQueue.__init_subclass__()
    oom_call("oc2m4:_pyrepl._module_completer.TokenQueue.__init_subclass__", getattr(oom_inst_oc2_tokenqueue, "__init_subclass__", None),
        -sys.maxsize,
    )
    # OOM sweep: TokenQueue.__ne__()
    oom_call("oc2m5:_pyrepl._module_completer.TokenQueue.__ne__", getattr(oom_inst_oc2_tokenqueue, "__ne__", None),
        "\uDC80",
    )
    del oom_inst_oc2_tokenqueue
    collect()

# OOM sweep: chain() constructor
oom_call("oc3:_pyrepl._module_completer.chain", getattr(fuzz_target_module, "chain", None),
)

oom_inst_oc3_chain = None
try:
    oom_inst_oc3_chain = callFunc("oc3_init", "chain",
    )
except Exception:
    oom_inst_oc3_chain = None

if oom_inst_oc3_chain is not None and oom_inst_oc3_chain is not SENTINEL_VALUE:
    # OOM sweep: chain.__setattr__()
    oom_call("oc3m1:_pyrepl._module_completer.chain.__setattr__", getattr(oom_inst_oc3_chain, "__setattr__", None),
        r"ljBhvF",
        {errback,
         None,
         -4246138335335528,
         b"\xD2\xB4\x86\x90\xAD\x7D"},
    )
    # OOM sweep: chain.__dir__()
    oom_call("oc3m2:_pyrepl._module_completer.chain.__dir__", getattr(oom_inst_oc3_chain, "__dir__", None),
    )
    # OOM sweep: chain.__repr__()
    oom_call("oc3m3:_pyrepl._module_completer.chain.__repr__", getattr(oom_inst_oc3_chain, "__repr__", None),
    )
    # OOM sweep: chain.__hash__()
    oom_call("oc3m4:_pyrepl._module_completer.chain.__hash__", getattr(oom_inst_oc3_chain, "__hash__", None),
    )
    # OOM sweep: chain.__repr__()
    oom_call("oc3m5:_pyrepl._module_completer.chain.__repr__", getattr(oom_inst_oc3_chain, "__repr__", None),
    )
    del oom_inst_oc3_chain
    collect()

# OOM sweep: TokenInfo() constructor
oom_call("oc4:_pyrepl._module_completer.TokenInfo", getattr(fuzz_target_module, "TokenInfo", None),
)

oom_inst_oc4_tokeninfo = None
try:
    oom_inst_oc4_tokeninfo = callFunc("oc4_init", "TokenInfo",
    )
except Exception:
    oom_inst_oc4_tokeninfo = None

if oom_inst_oc4_tokeninfo is not None and oom_inst_oc4_tokeninfo is not SENTINEL_VALUE:
    # OOM sweep: TokenInfo.__eq__()
    oom_call("oc4m1:_pyrepl._module_completer.TokenInfo.__eq__", getattr(oom_inst_oc4_tokeninfo, "__eq__", None),
        errback,
    )
    # OOM sweep: TokenInfo.__getstate__()
    oom_call("oc4m2:_pyrepl._module_completer.TokenInfo.__getstate__", getattr(oom_inst_oc4_tokeninfo, "__getstate__", None),
    )
    # OOM sweep: TokenInfo.__str__()
    oom_call("oc4m3:_pyrepl._module_completer.TokenInfo.__str__", getattr(oom_inst_oc4_tokeninfo, "__str__", None),
    )
    # OOM sweep: TokenInfo.__reduce_ex__()
    oom_call("oc4m4:_pyrepl._module_completer.TokenInfo.__reduce_ex__", getattr(oom_inst_oc4_tokeninfo, "__reduce_ex__", None),
        MagicMock,
    )
    # OOM sweep: TokenInfo.__class_getitem__()
    oom_call("oc4m5:_pyrepl._module_completer.TokenInfo.__class_getitem__", getattr(oom_inst_oc4_tokeninfo, "__class_getitem__", None),
        chr(255),
    )
    del oom_inst_oc4_tokeninfo
    collect()

# OOM sweep: ImportParser() constructor
oom_call("oc5:_pyrepl._module_completer.ImportParser", getattr(fuzz_target_module, "ImportParser", None),
    "\xE5\x80\xA6\xFCNd",
)

oom_inst_oc5_importparser = None
try:
    oom_inst_oc5_importparser = callFunc("oc5_init", "ImportParser",
        '/etc/machine-id',
    )
except Exception:
    oom_inst_oc5_importparser = None

if oom_inst_oc5_importparser is not None and oom_inst_oc5_importparser is not SENTINEL_VALUE:
    # OOM sweep: ImportParser.__getstate__()
    oom_call("oc5m1:_pyrepl._module_completer.ImportParser.__getstate__", getattr(oom_inst_oc5_importparser, "__getstate__", None),
    )
    # OOM sweep: ImportParser.__sizeof__()
    oom_call("oc5m2:_pyrepl._module_completer.ImportParser.__sizeof__", getattr(oom_inst_oc5_importparser, "__sizeof__", None),
    )
    # OOM sweep: ImportParser.__init_subclass__()
    oom_call("oc5m3:_pyrepl._module_completer.ImportParser.__init_subclass__", getattr(oom_inst_oc5_importparser, "__init_subclass__", None),
        r"fsH+ljPNC.\DCkHh.YF.Z",
    )
    # OOM sweep: ImportParser.__subclasshook__()
    oom_call("oc5m4:_pyrepl._module_completer.ImportParser.__subclasshook__", getattr(oom_inst_oc5_importparser, "__subclasshook__", None),
        r".W+.Ef\w\Bj+.E.p\Z.wPc\B",
    )
    # OOM sweep: ImportParser.parse_import()
    oom_call("oc5m5:_pyrepl._module_completer.ImportParser.parse_import", getattr(oom_inst_oc5_importparser, "parse_import", None),
    )
    del oom_inst_oc5_importparser
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

