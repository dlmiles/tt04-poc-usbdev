#
#
#
#
#
from enum import IntEnum


# FIXME auto-configure
EP_COUNT = 4
ADDRESS_LENGTH = 96 # 84
MAX_PACKET_LENGTH = 52 # 40


# Control Registers
REG_FRAME = 0xff00
REG_ADDRESS = 0xff04
REG_INTERRUPT = 0xff08
REG_HALT = 0xff0c
REG_CONFIG = 0xff10
REG_INFO = 0xff20 # aka CONFIG_WIDTH

# INTERRUPTS
INTR_EP0	= 0x00000001
INTR_EP1	= 0x00000002
INTR_EP2	= 0x00000004
INTR_EP3	= 0x00000008
INTR_RESET	= 0x00010000
INTR_EP0SETUP	= 0x00020000
INTR_SUSPEND    = 0x00040000
INTR_RESUME     = 0x00080000
INTR_DISCONNECT = 0x00100000


# Shared Memory Layout
REG_EP0 = 0x0000
REG_EP1 = 0x0004
REG_EP2 = 0x0008
REG_EP3 = 0x000c
REG_EPLAST = REG_EP0 + (EP_COUNT*4)

# FIXME move to register space 0xff18 0xff1c ?
REG_SETUP0 = 0x0010
REG_SETUP1 = 0x0014

BUF_START = 0x0020

BUF_DESC0_20 = 0x0020
BUF_DESC1_20 = 0x0024
BUF_DESC2_20 = 0x0028

BUF_DESC0_40 = 0x0040
BUF_DESC1_40 = 0x0044
BUF_DESC2_40 = 0x0048

BUF_DATA0_20 = 0x002c
BUF_DATA1_20 = 0x0030
BUF_DATA2_20 = 0x0034
BUF_DATA3_20 = 0x0038

BUF_DATA0_40 = 0x004c
BUF_DATA1_40 = 0x0050

BUF_END = 0x0000 + ADDRESS_LENGTH

# DESC0.code
DESC0_INPROGRESS = 0xf
DESC0_SUCCESS = 0x0
# DESC2.direction
DESC2_OUT = False
DESC2_IN = True

ADDR_DESC = {
    REG_FRAME: "REG_FRAME",
    REG_ADDRESS: "REG_ADDRESS",
    REG_INTERRUPT: "REG_INTERRUPT",
    REG_HALT: "REG_HALT",
    REG_CONFIG: "REG_CONFIG",
    REG_INFO: "REG_INFO",
    REG_EP0: "REG_EP0",
    REG_EP1: "REG_EP1",
    REG_EP2: "REG_EP2",
    REG_EP3: "REG_EP3",
    REG_SETUP0: "REG_SETUP0",
    REG_SETUP1: "REG_SETUP1",

    BUF_DESC0_20: "BUF_DESC0_20",
    BUF_DESC1_20: "BUF_DESC1_20",
    BUF_DESC2_20: "BUF_DESC2_20",
    BUF_DATA0_20: "BUF_DATA0_20",
    BUF_DATA1_20: "BUF_DATA1_20",
    BUF_DATA2_20: "BUF_DATA2_20",
    BUF_DATA3_20: "BUF_DATA3_20",

    BUF_DESC0_40: "BUF_DESC0_40",
    BUF_DESC1_40: "BUF_DESC1_40",
    BUF_DESC2_40: "BUF_DESC2_40",
    BUF_DATA0_40: "BUF_DATA0_40",
    BUF_DATA1_40: "BUF_DATA1_40",

    BUF_END: "BUF_END"
}

# This validate the design under test matches values here
def validate(dut) -> bool:
    # FIXME autoconfigure
    #ele = design_element(dut, "")
    #assert ele is None
    #assert ele.value == EP_COUNT, f""

    #ele = design_element(dut, "")
    #assert ele is None
    #assert ele.value == ADDRESS_LENGTH, f""

    #ele = design_element(dut, "")
    #assert ele is None
    #assert ele.value == MAX_PACKET_LENGTH, f""

    return True


class Reg(IntEnum):
    NONE = 0
    READ = 1
    WRITE = 2
    DEFAULT = 3
    ALL = 7

    def has(self, *values: int):
        for v in values:
            assert v is not Reg.NONE # only allowed on LHS
            if v == self.value or v is Reg.ALL:
                return True
        # All always matches
        return self is Reg.ALL


def reg_frame_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    if mode.has(Reg.READ):	# UVM=RO
        return "0x{:08x}".format(value)
    return None


def reg_address_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    if mode.has(Reg.WRITE):	# UVM=WO
        l = list()
        l.append("address=0x{:02x} {}".format(value & 0x7f, value & 0x7f))
        if value & 1 << 8:
            l.append("enable")
        if value & 1 << 9:
            l.append("trigger")
        return ', '.join(l)
    return None


def reg_interrupt_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    l = list()
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT) and value & 1 << 16:
        l.append("RESET")
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT) and value & 1 << 17:
        l.append("EP0")
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT) and value & 1 << 18:
        l.append("suspend")
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT) and value & 1 << 19:
        l.append("resume")
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT) and value & 1 << 20:
        l.append("disconnect")
    s = ', '.join(l)
    return "[{}] {}".format(
        format_reg_interrupt(value),
        s
    )


def reg_halt_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    # Many bits are UVM=WO
    l = list()
    if mode.has(Reg.WRITE) and value & 1 << 4:	# show when enable is set
        l.append("endp={}".format(value & 0xf))
    if mode.has(Reg.WRITE) and value & 1 << 4:
        l.append("enable-halt")
    if mode.has(Reg.READ, Reg.DEFAULT) and value & 1 << 5:
        l.append("effective_enable-halt")
    if mode.has(Reg.WRITE):
        if value & 1 << 4:
            l.append("HALT")
        else:
            l.append("RUN")
    nmenonic = "[{}] ".format(format_reg_halt(value)) if(mode.has(Reg.READ, Reg.WRITE)) else ''
    return nmenonic + ', '.join(l)


def reg_config_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    if mode.has(Reg.WRITE):
        l = list()
        if value & 1 << 0:
            l.append("pullset_set")
        if value & 1 << 1:
            l.append("pullset_clear")
        if value & 1 << 2:
            l.append("interrupt_enable_set")
        if value & 1 << 3:
            l.append("interrupt_enable_clear")
        return ', '.join(l)
    return None


# config_info
def reg_info_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode is Reg.NONE:
        return None
    if mode.has(Reg.READ, Reg.DEFAULT):	# UVM=RO
        l = list()
        l.append("addressWidth=0x{:02x} {}".format(value & 0xff, value & 0xff))
        l.append("epCount={}".format(((value >> 12) & 0xf) + 1))	# biased-by-1
        l.append("maxPacketLength={}".format(((value >> 16) & 0x1ff) + 1))	# biased-by-1
        l.append("spare={}".format((value >> 25) & 0x3))
        l.append("startOfBufferByteOffset={} ({})".format((value >> 27) & 0x1f, ((value >> 27) & 0x1f) << 2))
        return ', '.join(l)
    return None


def reg_setup_desc(value: int, which: int, mode: Reg = Reg.DEFAULT) -> str:
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT):
        s0 = (value >> 24) & 0xff
        s1 = (value >> 16) & 0xff
        s2 = (value >>  8) & 0xff
        s3 = (value >>  0) & 0xff
        return "setup{}=0x{:08x} [0x{:02x}, 0x{:02x}, 0x{:02x}, 0x{:02x}]".format(which, value, s3, s2, s1, s0)
    return None


def reg_endp_desc(value: int, mode: Reg = Reg.DEFAULT) -> str:
    l = list()
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT):
        if value & 1 << 0:
            l.append("enable")
        else:
            l.append("disable")
        if value & 1 << 1:
            l.append("stall")
        if value & 1 << 2:
            l.append("nak")
        if value & 1 << 3:
            l.append("data_phase_1")
        else:
            l.append("data_phase_0")
        head = (value >> 4) & 0xfff
        if head == 0:
            l.append("head=NONE")
        else:
            l.append("head=0x{:x} @0x{:x}".format(head, head << 4))
        if value & 1 << 16:
            l.append("isochronous")
        mps = (value >> 22) & 0x3ff
        l.append("max_packet_size={} (0x{:x})".format(mps, mps))
    return ', '.join(l)


def desc0_format(value: int, mode: Reg = Reg.DEFAULT) -> str:
    l = list()
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT):
        l.append("offset={:x}".format(value & 0xffff))
        l.append("code={:x}".format((value >> 16) & 0xf))
        if value & 0xfff00000 != 0:
            l.append("unused={:x}".format((value >> 20) & 0xfff))
    return ', '.join(l)


def desc1_format(value: int, mode: Reg = Reg.DEFAULT) -> str:
    l = list()
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT):
        l.append("next=0x{:x} @0x{:x}".format((value >> 4) & 0xfff, value & 0xfff0))
        l.append("length={} (0x{:x})".format((value >> 16) & 0xffff, (value >> 16) & 0xffff))
        if value & 0x0000000f != 0:
            l.append("unused={:x}".format(value & 0xf))
    return ', '.join(l)


def desc2_format(value: int, mode: Reg = Reg.DEFAULT) -> str:
    l = list()
    if mode.has(Reg.READ, Reg.WRITE, Reg.DEFAULT):
        if value & 1 << 16:
            l.append("IN")
        else:
            l.append("OUT")
        if value & 1 << 17:
            l.append("interrupt")
        if value & 1 << 18:
            l.append("completionOnFull")
        if value & 1 << 19:
            l.append("data1OnCompletion")
        if value & 0xfff0ffff != 0:
            l.append("unused={:x}".format(value & 0xfff0ffff))
    return ', '.join(l)


def addr_to_regname(addr: int) -> str:
    if addr in ADDR_DESC:
        return ADDR_DESC[addr]
    return None


def addr_to_regdesc(addr: int, value: int, mode: Reg = Reg.DEFAULT) -> str:
    if addr == REG_FRAME:
        return reg_frame_desc(value, mode)
    if addr == REG_ADDRESS:
        return reg_address_desc(value, mode)
    if addr == REG_INTERRUPT:
        return reg_interrupt_desc(value, mode)
    if addr == REG_HALT:
        return reg_halt_desc(value, mode)
    if addr == REG_CONFIG:
        return reg_config_desc(value, mode)
    if addr == REG_INFO:
        return reg_info_desc(value, mode)
    if addr == REG_SETUP0:
        return reg_setup_desc(value, 0, mode)
    if addr == REG_SETUP1:
        return reg_setup_desc(value, 1, mode)
    if addr >= REG_EP0 and addr <= REG_EPLAST:
        return reg_endp_desc(value, mode)
    return None

# Helper for wb_{read,write} that reverses the value/addr param order because it
#  was through this would allow operation specific value formatter or a general
#  purpose automatic lookup formatter to work by expecting the main argument
#  'value' 1st
def regdesc(value: int, addr: int, mode: Reg = Reg.DEFAULT) -> str:
    return addr_to_regdesc(addr, value, mode)

def regwr(value: int, addr: int) -> str:
    return addr_to_regdesc(addr, value, Reg.WRITE)

def regrd(value: int, addr: int) -> str:
    return addr_to_regdesc(addr, value, Reg.READ)


def REG_EP(value: int) -> int:
    assert value >= 0 and value <= 15, f"Invalid endpoint number: {value}"
    assert value <= EP_COUNT, f"Invalid endpoint number: {value} (exceeds hardware limit {EP_COUNT})"
    return REG_EP0 + (value * 4)


def addr_to_head(addr: int) -> int:
    # If you are getting asserted here this alignment restriction is part of hardware design
    assert addr % 16 == 0, f"addr = 0x{addr:04x} is not modulus 16"
    assert addr & ~0xffff == 0, f"addr = 0x{addr:04x} is not inside valid 16-bit range"
    return addr >> 4


def head_to_addr(head: int) -> int:
    assert head & ~0x0fff == 0, f"head = 0x{head:04x} is not inside valid 12-bit range"
    return head << 4


def desc0(
        offset: int = 0,
        code: int = DESC0_INPROGRESS
    ) -> int:
    val = 0
    assert offset & ~0xffff == 0, f"offset = 0x{offset:04x} is not inside valid 16-bit range"
    val |= offset & 0xffff
    assert code & ~0xf == 0, f"code = 0x{code:02x} is not inside valid 8-bit range"
    val |= (code & 0xf) << 16
    return val


def desc1(
        next: int = 0,
        length: int = 0
    ) -> int:
    val = 0
    assert next & ~0x0fff == 0, f"next = 0x{next:04x} is not inside valid 12-bit range"
    val |= (next & 0x0fff) << 4
    assert length & ~0xffff == 0, f"length = 0x{length:04x} is not inside valid 16-bit range"
    val |= (length & 0xffff) << 16
    return val


def desc2(
        direction: bool = DESC2_OUT,
        interrupt: bool = False,
        completionOnFull: bool = False,
        data1OnCompletion: bool = False
    ) -> int:
    val = 0
    if direction:
        val |= 0x00010000
    if interrupt:
        val |= 0x00020000
    if completionOnFull:
        val |= 0x00040000
    if data1OnCompletion:
        val |= 0x00080000
    return val


def reg_endp(
        enable: bool = False,
        stall: bool = False,
        nak: bool = False,
        data_phase: bool = False,
        head: int = 0, # 16byte alignment units
        isochronous: bool = False,
        max_packet_size: int = 0
    ) -> int:
    val = 0
    if enable:
        val |= 0x00000001	# bit0
    if stall:
        val |= 0x00000002	# bit1
    if nak:
        val |= 0x00000004	# bit2
    if data_phase:
        val |= 0x00000008	# bit3 (tracks DATA0/DATA1)
    assert head & ~0xfff == 0, f"head out of range {head}"
    val |= (head & 0xfff) << 4	# bit4..15 (12bits)
    if isochronous:
        val |= 0x00010000   # bit16
    assert max_packet_size & ~0x3ff == 0, f"max_packet_size out of range {max_packet_size}"
    val |= (max_packet_size & 0x3ff) << 22 # bit22..31 (10bits)
    return val


def reg_address(
        address: int = 0,
        enable: bool = False,
        trigger: bool = False
    ) -> int:
    val = 0
    assert (address & ~0x7f == 0), f"address is invalid and out of range {address}"
    val |= address & 0x7f  # bit0-6
    if enable:
        val |= 0x00000100  # bit8
    if trigger:
        val |= 0x00000200  # bit9
    return val


def reg_interrupt(
        endp: int = -1,
        reset: bool = False,
        ep0setup: bool = False,
        suspend: bool = False,
        resume: bool = False,
        disconnect: bool = False,
        all: bool = False
    ) -> int:
    val = 0
    assert endp == -1 or (endp >= 0 and endp <= 15), f"endp is invalid {endp}"
    if endp >= 0:
        val |= 1 << endp
    if reset:
        val |= 0x00010000
    if ep0setup:
        val |= 0x00020000
    if suspend:
        val |= 0x00040000
    if resume:
        val |= 0x00080000
    if disconnect:
        val |= 0x00100000
    if all:
        val |= 0x001fffff
    return val


def reg_halt(
        endp: int = 0,
        enable: bool = False,
        effective_enable: bool = False
    ) -> int:
    val = 0
    assert endp & ~0xf == 0, f"endp is {endp} and not a modulus of 4"
    val |= endp
    if enable:
        val |= 0x0010
    if effective_enable:
        val |= 0x0020
    return val


def reg_config(
        pullup_set: bool = False,
        pullup_clear: bool = False,
        interrupt_enable_set: bool = False,
        interrupt_enable_clear: bool = False
    ) -> int:
    val = 0
    if pullup_set:
        val |= 0x00000001
    if pullup_clear:
        val |= 0x00000002
    if interrupt_enable_set:
        val |= 0x00000004
    if interrupt_enable_clear:
        val |= 0x00000008
    return val


# addr argument ignored
def format_reg_interrupt(value: int, addr: int = None) -> str:
    s = ''
    for i in range(0, 15):
        if value & 1 << i:
            s += "{:1x}".format(i)
        else:
            s += "_"
    s += 'R' if value & 1 << 16 else '_'
    s += '0' if value & 1 << 17 else '_'
    s += 's' if value & 1 << 18 else '_'
    s += 'r' if value & 1 << 19 else '_'
    s += 'd' if value & 1 << 20 else '_'
    return s


# addr argument ignored
def format_reg_halt(value: int, addr: int = None) -> str:
    s = ''
    if(value & 1 << 4):
        s += "{:1x}".format(value & 0xf)	# WO write-only no readback
        s += 'e' if value & 1 << 4 else '_'	# WO write-only no readback
    else:
        s += '__'
    s += 'E' if value & 1 << 5 else '_'
    return s


__all__ = [
    'EP_COUNT',
    'ADDRESS_LENGTH',
    'MAX_PACKET_LENGTH',

    'validate',

    'REG_FRAME',
    'REG_ADDRESS',
    'REG_INTERRUPT',
    'REG_HALT',
    'REG_CONFIG',
    'REG_INFO',

    'REG_EP0',
    'REG_EP1',
    'REG_EP2',
    'REG_EP3',

    'REG_EP',	# function

    'REG_SETUP0',
    'REG_SETUP1',

    'INTR_EP0',
    'INTR_EP1',
    'INTR_EP2',
    'INTR_EP3',
    'INTR_RESET',
    'INTR_EP0SETUP',
    'INTR_SUSPEND',
    'INTR_RESUME',
    'INTR_DISCONNECT',

    'BUF_START',

    'BUF_DESC0_20',
    'BUF_DESC1_20',
    'BUF_DESC2_20',

    'BUF_DESC0_40',
    'BUF_DESC1_40',
    'BUF_DESC2_40',

    'BUF_DATA0_20',
    'BUF_DATA1_20',

    'BUF_DATA0_40',
    'BUF_DATA1_40',

    'BUF_END',

    'ADDR_DESC',

    'DESC0_INPROGRESS',
    'DESC0_SUCCESS',
    'DESC2_OUT',
    'DESC2_IN',

    'format_reg_halt',
    'format_reg_interrupt',

    'reg_frame_desc',
    'reg_address_desc',
    'reg_interrupt_desc',
    'reg_halt_desc',
    'reg_config_desc',
    'reg_info_desc',
    'reg_setup_desc',
    'reg_endp_desc',

    'regdesc',
    'regwr',
    'regrd',

    'addr_to_head',
    'head_to_addr',
    'addr_to_regname',
    'addr_to_regdesc',
    
    'desc0',
    'desc1',
    'desc2',
    
    'desc0_format',
    'desc1_format',
    'desc2_format',

    'reg_endp',
    'reg_address',
    'reg_interrupt',
    'reg_halt',
    'reg_config',

]
