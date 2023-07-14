#
#
#	Hmm when gate level testing with a flattened verilog, we loose all the
#	internal module structure.
#
#	But I want to still run my cocotb testing, just disable the parts that
#	are working on internal state.
#
#	So the solution ?  Make a 'dut' object proxy that returns a custom
#	super-class of cocotb.handle.NonHierarchyObject which will always have
#	a special 'P' state, if you ask for the value.
#	This will satisfy the codebase to run, when it is looking up a Python
#	object attribute reference, but you still need to mark the
#	tests/assertion to be skipped and the value 'P' should not match
#	anything expected.
#
#
#	If you ever heard of one version to throw away, this is it!
#	This is more a discovery on if the idea was possible and how to
#	get there, than how to do it elegantly or make the abstraction more
#	modular.
#
#
import re

import cocotb
from cocotb.handle import SimHandleBase, HierarchyObject, NonHierarchyObject
from cocotb.simulator import INTEGER


class FakeHandle():
    _name = None
    _type = None
    _def_name = None
    _def_file = None
    _len = None

    def __init__(self, name: str, handle_type: str, len: int = 1):
        #super().__init__(-1, name)	# SimHandleBase
        self._name = name
        self._type = handle_type
        self._len = len
        return None

    def __len__(self):
        return self.len

    def get_name_string(handle) -> str:
        assert isinstance(handle, FakeHandle)
        return handle._name

    def get_type_string(handle) -> str:
        assert isinstance(handle, FakeHandle)
        return handle._type

    def get_definition_name(handle) -> str:
        assert isinstance(handle, FakeHandle)
        return handle._def_name

    def get_definition_file(handle) -> str:
        assert isinstance(handle, FakeHandle)
        return handle._def_file



class DummyHandleObject(NonHierarchyObject):
    handle = None
    path = None
    handle_type = None
    value = None

    def __init__(self, handle, path, handle_type, value) -> None:
        super().__init__(handle, path)
        self.handle_type = handle_type
        self.value = value
        return None

    def get_value(self) -> str:
        return self.value

    def __getattribute__(self, name):
        self_path = object.__getattribute__(self, "path")
        print(f"DummyHandleObject.__getattribute__(path={self_path} name={name}) {type(name)}")
        try:
            retval = object.__getattribute__(self, name)
        except AttributeError as exc:
            if True:	# can apply filter action here
                path = self_path + '.' + name if(self_path) else name
                h = FakeHandle(path, INTEGER)
                return DummyHandleObject(h, h.get_name_string(), INTEGER, DEFAULT_VALUE)
            raise exc

        return retval


DEFAULT_VALUE = 'P'

# Python Proxy Receipe taken from:
#  Python Software Foundation License
#  Created by tomer filiba on Fri, 26 May 2006 (PSF)
class ProxyDut(object):
    __slots__ = ["_obj", "_hierarchy_path", "_proxy_cache", "_proxy_match_re", "_proxy_match_name_re", "__weakref__"]


    def __init__(self, obj, hierarchy_path: str = None) -> None:
        print(f"ProxyDut.__init__({type(obj)}, hierarchy_path={hierarchy_path})")
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_hierarchy_path", hierarchy_path)
        object.__setattr__(self, "_proxy_cache", {})

        _match_re = []
        for repattern in [
            r'^clk$',
            r'^ena$',
            r'^rst_n$',
            r'^ui_in$',
            r'^uo_out$',
            r'^uio_in$',
            r'^uio_out$',
            r'^uio_oe$'
        ]:
            _match_re.append(re.compile(repattern))
        object.__setattr__(self, "_proxy_match_re", _match_re)

        _match_name_re = []
        for repattern in [
            r'^dut\.tt2wb$'
        ]:
            _match_name_re.append(re.compile(repattern))
        object.__setattr__(self, "_proxy_match_name_re", _match_name_re)

        return None


    def _proxy_match(self, path) -> bool:
        for recomp in object.__getattribute__(self, "_proxy_match_re"):
            if recomp.search(path):	# match() ?
                return True
        return False


    def _proxy_match_name(self, path) -> bool:
        for recomp in object.__getattribute__(self, "_proxy_match_name_re"):
            print(f"ProxyDut._proxy_match_name(path={path}) {type(path)} with {recomp}")
            if recomp.search(path):	# match() ?
                return True
        return False


    def __proxy_getattribute__(self, name, exc):
        print(f"ProxyDut.__proxy_getattribute__(name={name}, exc={exc}) {type(name)}")

        cache = object.__getattribute__(self, "_proxy_cache")
        if path in cache:
            return cache[path]

        if not self._proxy_match(path):
            raise exc

        # FIXME maybe we should add a filter here of what is allowed, handle_type, value
        handle = DummyHandleObject(None, path, INTEGER, DEFAULT_VALUE)
        cache[path] = handle
        return handle

    @staticmethod
    def __proxy_namespace_mutator(ns):
        #assert isinstance(INTEGER, str), f"INTEGER={type(INTEGER)} {str(INTEGER)}"
        h = FakeHandle('ttwb', INTEGER)
        ns['get_tt2wb'] = DummyHandleObject(h, h.get_name_string(), INTEGER, DEFAULT_VALUE)
        return ns


    #
    # proxying (special cases)
    #
    def __getattribute__(self, name):
        try:
            #if getattr(object.__getattribute__(self, "_obj"), "_proxy_match_name")(name):
            #    retval = getattr(object.__getattribute__(self, "_obj"), name)
            #else:
            retval = getattr(object.__getattribute__(self, "_obj"), name)
        except AttributeError as exc:
            print(f"ProxyDut.__getattribute__(name={name}) {type(name)}")
            pm = object.__getattribute__(self, "_proxy_match_name")
            hierarchy_path = object.__getattribute__(self, "_hierarchy_path")
            path = hierarchy_path + '.' + name if(hierarchy_path) else name
            rv = pm(path)
            if rv:	# if it is a toplevel match return Fake
                print(f"ProxyDut.__getattribute__(name={name}) {type(name)} = {exc} {pm} {rv} INJECT FAKE")
                h = FakeHandle(path, INTEGER)
                return DummyHandleObject(h, h.get_name_string(), INTEGER, DEFAULT_VALUE)
            print(f"ProxyDut.__getattribute__(name={name}) {type(name)} = {exc} {pm} {rv}")
            raise exc

        if isinstance(retval, HierarchyObject):
            retval = ProxyDut(retval, name)	# wrap
            #func = getattr(object.__getattribute__(self, "_obj"), "__proxy_getattribute__")
            #if func:
            #    return func(name, exc)
        
        return retval

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, "_obj"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_obj"), name, value)

    def __nonzero__(self):
        return bool(object.__getattribute__(self, "_obj"))
    def __str__(self):
        return str(object.__getattribute__(self, "_obj"))
    def __repr__(self):
        return repr(object.__getattribute__(self, "_obj"))

    def __unicode__(self):
        return unicode(object.__getattribute__(self, "_obj"))
    
    def __hash__(self):
        return hash(object.__getattribute__(self, "_obj"))
    
    #
    # factories
    #
    _special_names = [
        '__abs__', '__add__', '__and__', '__call__', '__cmp__', '__coerce__', 
        '__contains__', '__delitem__', '__delslice__', '__div__', '__divmod__', 
        '__eq__', '__float__', '__floordiv__', '__ge__', '__getitem__', 
        '__getslice__', '__gt__',
        #'__hash__',
        '__hex__', '__iadd__', '__iand__',
        '__idiv__', '__idivmod__', '__ifloordiv__', '__ilshift__', '__imod__', 
        '__imul__', '__int__', '__invert__', '__ior__', '__ipow__', '__irshift__', 
        '__isub__', '__iter__', '__itruediv__', '__ixor__', '__le__', '__len__', 
        '__long__', '__lshift__', '__lt__', '__mod__', '__mul__', '__ne__', 
        '__neg__', '__oct__', '__or__', '__pos__', '__pow__', '__radd__', 
        '__rand__', '__rdiv__', '__rdivmod__', '__reduce__', '__reduce_ex__', 
        '__repr__', '__reversed__', '__rfloorfiv__', '__rlshift__', '__rmod__', 
        '__rmul__', '__ror__', '__rpow__', '__rrshift__', '__rshift__', '__rsub__', 
        '__rtruediv__', '__rxor__', '__setitem__', '__setslice__', '__sub__', 
        '__truediv__', '__xor__', 'next',
    ]
    
    @classmethod
    def _create_class_proxy(cls, theclass):
        """creates a proxy for the given class"""
        
        def make_method(name):
            def method(self, *args, **kw):
                return getattr(object.__getattribute__(self, "_obj"), name)(*args, **kw)
            return method
        
        namespace = {}
        for name in cls._special_names:
            if hasattr(theclass, name):
                namespace[name] = make_method(name)
        namespace = cls.__proxy_namespace_mutator(namespace)
        return type("%s(%s)" % (cls.__name__, theclass.__name__), (cls,), namespace)
    
    def __new__(cls, obj, *args, **kwargs):
        """
        creates an proxy instance referencing `obj`. (obj, *args, **kwargs) are
        passed to this class' __init__, so deriving classes can define an 
        __init__ method of their own.
        note: _class_proxy_cache is unique per deriving class (each deriving
        class must hold its own cache)
        """
        try:
            cache = cls.__dict__["_class_proxy_cache"]
        except KeyError:
            cls._class_proxy_cache = cache = {}
        try:
            theclass = cache[obj.__class__]
        except KeyError:
            cache[obj.__class__] = theclass = cls._create_class_proxy(obj.__class__)
        ins = object.__new__(theclass)
        theclass.__init__(ins, obj, *args, **kwargs)
        return ins



__all__ = [
    'ProxyDut'
]
