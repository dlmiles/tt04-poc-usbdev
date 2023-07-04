#
#
#
#
#
#
import cocotb
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


# BinaryValue can have Z and X states so sometime we just want to extract 1 bit
# TODO make a version for multiple bits/mask
def extract_bit(v, bit: int) -> bool:
    assert(bit >= 0)
    assert type(v) is BinaryValue or type(v) is int or type(v) is bool
    if type(v) is int:
        v = BinaryValue(v, n_bits=v.bit_length())
    if type(v) is bool:
        v = BinaryValue(v, n_bits=1)
    if type(v) is BinaryValue:
        s = v.binstr
        if bit+1 > v.n_bits:
            raise Exception(f"{bit+1} > {v.n_bits} from {v}")
        p = s[-(bit+1)]
        #print("extract_bit {} {} {} {} {} p={}".format(v, s, s[-(bit+2)], s[-(bit+1)], s[-(bit)], p))
        return True if(p == '1') else False
    raise Exception(f"type(v) is not a type we understand: {type(v)}")


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

    'debug',

    'extract_bit'
]
