#
#
#
#  SpinalHDL UsbDevice bus transaction helper
#
#  FIXME separate the WishBone to test_wishbone.py
#
#
import os

# Control Registers
REG_FRAME = 0xff00
REG_ADDRESS = 0xff04
REG_INTERRUPT = 0xff08
REG_HALT = 0xff0c
REG_CONFIG = 0xff10
REG_INFO = 0xff20


# Shared Memory Layout
BUF_EP0 = 0x0000
BUF_EP1 = 0x0004

BUF_SETUP0 = 0x0008
BUF_SETUP1 = 0x000c

BUF_DESC0 = 0x0010
BUF_DESC1 = 0x0014
BUF_DESC2 = 0x0018

BUF_DATA0 = 0x0020
BUF_DATA1 = 0x0024
BUF_DATA2 = 0x0028
BUF_DATA3 = 0x002c

BUF_END = 0x0030

ADDR_DESC = {
    REG_FRAME: "REG_FRAME",
    REG_ADDRESS: "REG_ADDRESS",
    REG_INTERRUPT: "REG_INTERRUPT",
    REG_HALT: "REG_HALT",
    REG_CONFIG: "REG_CONFIG",
    REG_INFO: "REG_INFO",
    BUF_EP0: "BUF_EP0",
    BUF_EP1: "BUF_EP1",
    BUF_SETUP0: "BUF_SETUP0",
    BUF_SETUP1: "BUF_SETUP1",
    BUF_DESC0: "BUF_DESC0",
    BUF_DESC1: "BUF_DESC1",
    BUF_DESC2: "BUF_DESC2",
    BUF_DATA0: "BUF_DATA0",
    BUF_DATA1: "BUF_DATA1",
    BUF_DATA2: "BUF_DATA2",
    BUF_DATA3: "BUF_DATA3",
    BUF_END: "BUF_END"
}


def addr_desc(addr: int, unknown: bool = False) -> str:
    if addr in ADDR_DESC:
        return ADDR_DESC.get(addr)
    if unknown:
        return None
    return "%04x".format(addr)


async def wb_wait_ACK(dut) -> bool:
    max_iter = 5000
    while dut.dut.wb_ACK.value == 0 and max_iter > 0:
        max_iter -= 1
        await ClockCycle(dut.clk, 1)
    if max_iter <= 0:
        raise Exception()
    return dut.dut.wb_ACK.value == 1


async def wb_write(dut, addr: int, value: int) -> None:
    assert addr % 4 == 0, f"addr = $addr not aligned to modulus 4"
    dut.wb_CYC.value = 1
    dut.wb_STB.value = 1
    dut.wb_WE.value = 1
    dut.wb_SEL.value = 0xf	# 4 bits (32bit write)
    dut.wb_ADR.value = addr
    dut.wb_DAT_MOSI.value = value

    dut._log.info("%s(0x%04x) = 0x%08x WRITE", addr_desc(addr), addr, data)

    await wb_wait_ACK(dut)

    dut.wb_STB.value = 0
    dut.wb_WE.value = 0
    dut.wb_SEL.value = 0
    await ClockCycle(dut.clk, 1)


async def wb_read(dut, addr: int) -> int:
    assert addr % 4 == 0, f"addr = $addr not aligned to modulus 4"
    dut.wb_CYC.value = 1
    dut.wb_STB.value = 1
    dut.wb_WE.value = 0
    dut.wb_SEL.value = 0x0
    dut.wb_ADR.value = addr

    # FIXME async this with timeout/iteration limit
    while dut.dut.wb_ACK.value == 0:
        await ClockCycle(dut.clk, 1)

    retval = dut.wb_DAT_MISO.value
    dut.wb_STB.value = 0
    await ClockCycle(dut.clk, 1)
    dut._log.info("%s(0x%04x) = 0x%08x READ", addr_desc(addr), addr, data)
    return retval


async def wb_dump(dut, addr: int, count: int) -> None:
    assert addr % 4 == 0, f"addr = $addr not aligned to modulus 4"
    assert count % 4 == 0, f"count = $count not aligned to modulus 4"
    while count > 0:
        wb_read(dut, addr)
        count -= 4
        addr += 4


def build_endp(
        enable: bool = False,
        stall: bool = False,
        nack: bool = False,
        data_phase: bool = False,
        head: int = 0,
        isochronous: bool = False,
        max_packet_size: int = 0
    ) -> int:
    val = 0
    if enable:
        val |= 0x00001	# bit0
    if stall:
        val |= 0x00002	# bit1
    if nack:
        val |= 0x00004	# bit2
    if data_phase:
        val |= 0x00008	# bit3
    assert head & ~0xfff == 0, f"head out of range $head"
    val |= (head & 0xfff) << 4	# bit4..15 (12bits)
    if isochronous:
        val |= 0x10000   # bit16
    assert max_packet_size & ~0x3ff == 0, f"max_packet_size out of range $max_packet_size"
    val |= (max_packet_size & 0x3ff) << 22 # bit22..31 (10bits)
    return val


def build_interrupt(
        endp: int = -1,
        reset: bool = False,
        ep0Setup: bool = False,
        suspend: bool = False,
        resume: bool = False,
        disconnect: bool = False,
        all: bool = False
    ) -> int:
    val = 0
    assert endp == -1 or (endp >= 0 and endp <= 15), f"endp is invalid $endp"
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


def build_halt(
        endp: int = 0,
        enable: bool = False,
        effective_enable: bool = False
    ) -> int:
    val = 0
    assert endp & ~0xf == 0, f"endp is $endp and not a modulus of 4"
    val |= endp
    if enable:
        val |= 0x0010
    if effective_enable:
        val |= 0x0020
    return val


def build_config(
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


def dump_reg_interrupt(value: int) -> str:
    s = ''
    for i in range(0, 15):
        if value and 1 << i:
            s += "%x".format(i)
        else:
            s += "_"
    s += 'R' if value and 1 << 16 else '_'
    s += '0' if value and 1 << 17 else '_'
    s += 's' if value and 1 << 18 else '_'
    s += 'r' if value and 1 << 19 else '_'
    s += 'd' if value and 1 << 20 else '_'
    return s


def dump_reg_halt(value: int) -> str:
    s = ''
    s += "%x".format(value and 0xf)		# WO write-only no readback
    s += 'e' if value and 1 << 4 else '_'	# WO write-only no readback
    s += 'E' if value and 1 << 5 else '_'
    return s


def setup(dut):
    # role call on registers
    data = wb_read(dut, REG_FRAME)

    data = wb_read(dut, REG_ADDRESS)

    data = wb_read(dut, REG_INTERRUPT)

    data = wb_read(dut, REG_HALT)

    data = wb_read(dut, REG_CONFIG)

    data = wb_read(dut, REG_INFO)


    wb_dump(dut, BUF_EP0, BUF_END)


    # ENDPOINT#0
    wb_write(dut, REG_HALT, build_halt(endp=0)) # HALT EP=0

    # Not needed but we do it to peek at state
    data = wb_read(dut, REG_HALT)

    wb_write(dut, BUF_EP0, build_endp(enable=True)) #

    wb_write(dut, REG_HALT, build_halt(endp=0, enable=True)) # HALT EP=0 (unhalt)


    # ENDPOINT#1
    wb_write(dut, REG_HALT, build_halt(endp=1)) # HALT EP=1

    # Not needed but we do it to peek at state
    data = wb_read(dut, REG_HALT)

    wb_write(dut, BUF_EP1, build_endp(enable=True)) #

    wb_write(dut, REG_HALT, build_halt(endp=1, enable=True)) # HALT EP=1 (unhalt)


    # CLEAR INTERRUPTS
    wb_write(dut, REG_INTERRUPTS, build_interrupt(all=True))


    # ENABLE INTERRUPTS
    wb_write(dut, REG_CONFIG, build_config(interrupt_enable_set=True))



async def wait_for_interrupt(dut) -> int:
    while dut.interrupt.value == 0:
        await ClockCycle(dut.clk, 1)

    if dut.interrupt.value == 0:
        return None

    value = wb_read(dut, REG_INTERRUPT)
    dump_reg_interrupt(dut, value)

    return value
