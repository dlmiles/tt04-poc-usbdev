#
#
#
#
#
#
from typing import Any, Callable
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue



def try_integer(v, default_value=None) -> int:
    if type(v) is int:
        return v
    if v.is_resolvable:
        return v.integer
    if default_value is not None:
        return default_value
    return v

def try_binary(v, width=None):
    if type(v) is BinaryValue:
        return v
    if type(v) is str:	## remind myself of the use case ? this look like an error or bad design
        return v
    if width is None:
        return BinaryValue(v)
    else:
        return BinaryValue(v, n_bits=width)




# Useful when you want a particular format, but only if it is a number
#  try_decimal_format(valye, '3d')
def try_decimal_format(v, fmt=None) -> str:
    #print("try_decimal_format(v={} {}, fmt={} {})".format(v, type(v), fmt, type(fmt)))
    if fmt is not None and type(v) is int:
        fmtstr = "{{0:{}}}".format(fmt)
        #print("try_decimal_format(v={} {}, fmt={} {})  fmtstr=\"{}\" => \"{}\"".format(v, type(v), fmt, type(fmt), fmtstr, fmtstr.format(v)))
        return fmtstr.format(v)
    return "{}".format(v)

def try_compare_equal(a, b) -> bool:
    a_s = str(try_binary(a))	# string
    b_s = str(try_binary(b))
    rv = a_s == b_s
    #print("{} {} == {} {} => {}".format(a, a_s, b, b_s, rv))
    return rv

def try_name(v) -> str:
    if v is None:
        return None
    if hasattr(v, '_name'):
        return v._name
    return str(v)

def try_path(v) -> str:
    if v is None:
        return None
    if hasattr(v, '_path'):
        return v._path
    return str(v)

def try_value(v) -> str:
    if v is None:
        return None
    if hasattr(v, 'value'):
        return v.value
    return str(v)

def report_resolvable(dut, pfx = None, node = None, depth = None, filter = None) -> None:
    if depth is None:
        depth = 3
    if depth < 0:
        return
    if node is None:
        node = dut
        if pfx is None:
            pfx = "DUT."
    if pfx is None:
        pfx = ""
    for design_element in node:
        if isinstance(design_element, cocotb.handle.ModifiableObject):
            if filter is None or filter(design_element._path, design_element._name):
                dut._log.info("{}{} = {}".format(pfx, design_element._name, design_element.value))
        elif isinstance(design_element, cocotb.handle.HierarchyObject) and depth > 0:
            report_resolvable(dut, pfx + try_name(design_element) + '.', design_element, depth=depth - 1, filter=filter)	# recurse
        else:
            if filter is None or filter(design_element._path, design_element._name):
                dut._log.info("{}{} = {} {}".format(pfx, try_name(design_element), try_value(design_element), type(design_element)))
    pass


# Does not nest
def design_element_internal(dut_or_node, name):
    #print("design_element_internal(dut_or_node={}, name={})".format(dut_or_node, name))
    for design_element in dut_or_node:
        #print("design_element_internal(dut_or_node={}, name={}) {} {}".format(dut_or_node, name, try_name(design_element), design_element))
        if design_element._name == name:
            return design_element
    return None

# design_element(dut, 'module1.module2.signal')
def design_element(dut, name):
    names = name.split('.')	# will return itself if no dot
    #print("design_element(name={}) {} len={}".format(name, names, len(names)))
    node = dut
    for name in names:
        node = design_element_internal(node, name)
        if node is None:
            return None
    return node

def design_element_exists(dut, name) -> bool:
    return design_element(dut, name) is not None


async def clockcycles_with_progress(dut,
    total_ticks: int,
    ticks_per_iteration: int,
    progress: Callable[[int],str],
    before: Callable[[int],str]
) -> None:

    assert total_ticks > 0
    assert ticks_per_iteration > 0

    ticks = 0
    if total_ticks > ticks_per_iteration:
        if before:
            dut._log.info(before(0))

        for i in range(0, int(total_ticks / ticks_per_iteration)):
            await ClockCycles(dut.clk, ticks_per_iteration)
            ticks += ticks_per_iteration
            if progress:
                dut._log.info(progress(ticks))

        left = total_ticks - ticks
        if left > 0:	# just in case there is a remainder
            await ClockCycles(dut.clk, left)
    elif total_ticks > 0:
        await ClockCycles(dut.clk, total_ticks)


def debug(dut, value: str, ele_name='DEBUG', mode: int = 8) -> None:
    assert mode == 7 or mode == 8
    ele = design_element(dut, ele_name)
    assert ele is not None, f"debug can not find signal: {ele_name}"
    #print("{}".format(str(ele.value)))
    #print("{}".format(ele.value.buff.decode('ascii')))
    bitlen = ele.value.n_bits
    assert bitlen % mode == 0, f"signal {ele_name} is n_bits={bitlen} which is not modulus {mode} for ASCII"
    maxcharlen = int(bitlen / mode)
    assert mode == 8	## FIXME encode and pack 7bit ascii
    if len(value) > maxcharlen:
        dut._log.warning("debug({}) len={} is longer than max characters {} for {} bits of signal: {}".format(value, len(value), maxcharlen, bitlen, ele_name))
        value = value[0:maxcharlen]
    asbytes = value.ljust(maxcharlen).encode('ascii')
    #print("len={} {} {}".format(maxcharlen, type(asbytes), asbytes))
    ele.value = BinaryValue(asbytes)
    dut._log.debug("debug({})".format(value))



def default_mapper(s: str) -> bool:
    # Only 1 is true all else if False
    return True if(s == '1') else False


# BinaryValue can have Z and X states so sometime we just want to extract 1 bit
# TODO make a version for multiple bits/mask
def binary_value_bit(bv: BinaryValue, bitid: int, value: Any = None, mapper: Callable[[str],bool] = None) -> bool:
    assert bitid >= 0
    assert isinstance(bv, BinaryValue)

    s = bv.binstr
    biti = bitid+1 # 1-based index
    if biti > bv.n_bits:
        raise Exception(f"{biti} > {bv.n_bits} from {bv}")
    # The minus characters are due to bit0 being at the right-hand-side
    msb = s[:-(biti)]
    lsb = s[-(biti-1):]
    p = s[-(biti)]

    dbg1 = "{} {} {}".format(s[-(biti+1)], s[-(biti)], s[-(biti-1)]) if(bv.n_bits > bitid+1) else "small={}".format(bv.n_bits)
    dbg2 = "{} {} {} {}".format(dbg1, msb, p, lsb)

    if value is not None:
        if isinstance(value, bool):
            bitstr = '1' if(value) else '0'
        else:
            bitstr = str(value)
        nvstr = msb + bitstr + lsb
        #print("binary_value_bit {} {} {} {} SET {} {} => {}".format(value, bitid, s, dbg2, value, bitstr, nvstr))
        assert len(s) == len(nvstr)
        nv = BinaryValue(nvstr, n_bits=bv.n_bits)
        assert nv.n_bits == bv.n_bits
    else:
        #print("binary_value_bit {} {} {} {} GET".format(value, bitid, s, dbg2))
        nv = bv

    if mapper:
        return (nv, mapper(p), p)
    else:
        return (nv, default_mapper(p), p)


def extract_bit(v, bitid: int) -> bool:
    assert(bitid >= 0)
    if isinstance(v, cocotb.handle.NonHierarchyObject):
        v = v.value
    assert isinstance(v, BinaryValue) or isinstance(v, int) or isinstance(v, bool), f"extract_bit() value not a supported type: {type(v)}"
    if type(v) is int:
        v = BinaryValue(v, n_bits=v.bit_length())
    if type(v) is bool:
        v = BinaryValue(v, n_bits=1)
    if type(v) is BinaryValue:
        (nbv, mv, sv) = binary_value_bit(v, bitid)
        return mv
    raise Exception(f"type(v) is not a type we understand: {type(v)}")


def change_bit(signal, bitid: int, bf: bool) -> bool:
    assert(bitid >= 0 and bitid <= 32)
    assert isinstance(signal, cocotb.handle.ModifiableObject), f"{type(signal)} is not the expected type {type(cocotb.handle.ModifiableObject)}"
    v = signal.value
    if type(v) is BinaryValue:
        (nbv, mv, sv) = binary_value_bit(v, bitid, bf)
        signal.value = nbv
        return mv
    raise Exception(f"type(v) is not a type we understand: {type(v)}")


def clear_bit(signal, bitid: int) -> bool:
    return change_bit(signal, bitid, False)


def set_bit(signal, bitid: int) -> bool:
    return change_bit(signal, bitid, True)



__all__ = [
    'try_integer',
    'try_binary',
    'try_decimal_format',
    'try_compare_equal',
    'try_name',
    'try_path',
    'try_value',
    'report_resolvable',

    'design_element_internal',
    'design_element',
    'design_element_exists',

    'clockcycles_with_progress',

    'debug',

    'extract_bit',
    'clear_bit',
    'set_bit',
    'change_bit'
]
