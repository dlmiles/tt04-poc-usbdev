#
#
#
#
#
#
import os
import random

import cocotb
from cocotb.binary import BinaryValue
from cocotb.handle import NonHierarchyObject, ModifiableObject
from cocotb.triggers import ClockCycles
from usbtester.cocotbutil import *
from usbtester.TT2WB import TT2WB, ADR_MASK, CMD_IDLE, CMD_EXEC, CMD_AD0, CMD_AD1, CMD_DO0, CMD_DO3, CMD_DI0, CMD_DI3, EXE_RESET, EXE_WBSEL, EXE_DISABLE, EXE_ENABLE, EXE_READ, EXE_WRITE, ACK_BITID


# This is used as detection of gatelevel testing, with a flattened HDL,
#  we can only inspect the external module signals and disable internal signal inspection.
GL_TEST = ('GL_TEST' in os.environ and os.environ['GL_TEST'] != 'false') or ('GATES' in os.environ and os.environ['GATES'] != 'no')


def format_value(v) -> str:
    if isinstance(v, cocotb.handle.NonHierarchyObject):
        value = v.value
        if isinstance(value, BinaryValue):
            if value.is_resolvable:
                return f"b{str(value.binstr)} 0x{value.integer:x}"
            else:
                return f"b{str(value.binstr)}"
    return f"{str(v)} isi={isinstance(v, BinaryValue)} t={type(v)}"


def format_assert(signal, expected) -> str:
    path = signal._path
    signal_desc = format_value(signal)
    expected_desc = format_value(expected)
    return f"{signal._path}: actual {signal_desc} != {expected_desc} expected"


def DO_ASSERT(signal, expected) -> None:
    assert isinstance(signal, NonHierarchyObject), f"Unexpected type: {type(signal)}"
    # Ideally we could do with the stacktrace returned being the callers (not here)
    assert signal.value == expected, format_assert(signal, expected)


async def test_tt2wb_cooked(dut):
    tt2wb = TT2WB(dut)

    await tt2wb.exe_reset()

    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, 0)
        DO_ASSERT(dut.dut.tt2wb.DO, 0)
        DO_ASSERT(dut.dut.tt2wb.DI, 0)
        DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)
        DO_ASSERT(dut.dut.tt2wb.CYC, 0)
        DO_ASSERT(dut.dut.tt2wb.STB, 0)
        DO_ASSERT(dut.dut.tt2wb.WE, 0)

    dut.uio_in.value = 0x00
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)

    await tt2wb.exe_enable()

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.CYC, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_CYC, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    addr = 0xfedc		# (addr is 14bit, addr_to_bus(0xfedc) = 0x3fb7)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0xba98		# (addr is 14bit, addr_to_bus(0xba98) = 0x2ea6)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0x3210		# (addr is 14bit, addr_to_bus(0x3210) = 0x0c84)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0x7654		# (addr is 14bit, addr_to_bus(0x7654) = 0x1d95)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    data = 0xfedcba98
    ack = await tt2wb.exe_write(data)
    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.DO, data)
        DO_ASSERT(dut.dut.tt2wb.wb_DAT_MOSI, data)

    assert ack, f"wb_ACK = {ack}"

    await tt2wb.exe_enable()
    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    assert not tt2wb.is_ack(), f"wb_ACK = {ack}"    

    ack = await tt2wb.exe_write(data)
    assert ack, f"wb_ACK = {ack}"

    await tt2wb.exe_enable()
    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    assert not tt2wb.is_ack(), f"wb_ACK = {ack}"

    readdata = await tt2wb.exe_read()
    assert ack, f"wb_ACK = {ack}"

    await tt2wb.exe_enable()

    await tt2wb.exe_reset()

    await tt2wb.exe_enable()

    #################################################################################

    await tt2wb.exe_wbsel(0)		# WBSEL

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0)

    await tt2wb.exe_wbsel(0x5)		# WBSEL

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0x5)

    # WRITE (with wb_SEL=0x5)
    ack = await tt2wb.exe_write(None, None, None, wait_ack=False)
    assert ack is None

    # manual wait for ACK to control number of cycles
    ack = await tt2wb.wb_ACK_wait(cycles=1, can_raise=False)
    assert ack == False

    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x5)
        DO_ASSERT(dut.dut.tt2wb.wb_WE, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 1)

    # as is allowed the device has been issued write and we are waiting multicycles to see ACK
    ack = await tt2wb.wb_ACK_wait(cycles=None)
    assert ack, f"wb_ACK = {ack}"

    # we already clocked it one more to see it (to also see the ACK)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x0)
        DO_ASSERT(dut.dut.tt2wb.wb_WE, 0)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    await tt2wb.exe_reset()		# EXE_RESET (should set 0xf)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)

    #################################################################################

    await tt2wb.exe_reset()

    await ClockCycles(dut.clk, 16)
    #assert False, f"STOP"


# testing tt04_to_wishbone.v
async def test_tt2wb_raw(dut):
    tt2wb = TT2WB(dut)

    # The raw version of the test
    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_RESET		# EXE_RESET
    await ClockCycles(dut.clk, 1)

    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, 0)
        DO_ASSERT(dut.dut.tt2wb.DO, 0)
        DO_ASSERT(dut.dut.tt2wb.DI, 0)
        DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)
        DO_ASSERT(dut.dut.tt2wb.CYC, 0)
        DO_ASSERT(dut.dut.tt2wb.STB, 0)
        DO_ASSERT(dut.dut.tt2wb.WE, 0)

    dut.uio_in.value = 0x00
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)


    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.CYC, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_CYC, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    addr = 0xfedc		# (addr is 14bit, addr_to_bus(0xfedc) = 0x3fb7)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0xdc	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0xfe	# AD1
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0xba98		# (addr is 14bit, addr_to_bus(0xba98) = 0x2ea6)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0x98	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0xba	# AD0 (double, into high-half)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0x3210		# (addr is 14bit, addr_to_bus(0x3210) = 0x0c84)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x32	# AD1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x10	# AD1 (double, into low-half)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    addr = 0x7654		# (addr is 14bit, addr_to_bus(0x7654) = 0x1d95)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0x54	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x76	# AD1
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.ADR, addr)
    expected = tt2wb.addr_to_bus(addr)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_ADR, expected)


    data = 0xfedcba98
    dut.uio_in.value = CMD_DO0
    dut.ui_in.value = 0x98	# DO0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO0
    dut.ui_in.value = 0xba	# DO1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO0
    dut.ui_in.value = 0xdc	# DO2
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO0
    dut.ui_in.value = 0xfe	# DO3
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.DO, data)
        DO_ASSERT(dut.dut.tt2wb.wb_DAT_MOSI, data)


    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_WRITE		# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_WRITE		# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    addr = 0xff20		# REG_INFO know return value
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0xff	# AD1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x20	# AD0
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_READ		# EXE_READ
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

    # DI0 use test (these CMD_IDLE insertions are not needed, but validate output hold)
    do_insert_IDLE = bool(random.getrandbits(1))  # False

    d0 = dut.uo_out.value	# DI0
    assert d0 == 0x07	# AddressWidth == 7
    #assert d0 == 0x06	# AddressWidth == 6

    dut.uio_in.value = CMD_DI0
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 2)
    else:
        await ClockCycles(dut.clk, 1)	# pipeline setup
    d1 = dut.uo_out.value	# DI1

    dut.uio_in.value = CMD_DI0
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 3)
    d2 = dut.uo_out.value	# DI2

    dut.uio_in.value = CMD_DI0
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 4)
    d3 = dut.uo_out.value	# DI3

    # Don't need to do this, but checking it went back around to d0
    dut.uio_in.value = CMD_DI0
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 5)
    assert dut.uo_out.value == d0, f"{str(dut.uo_out.value)} != {d0} do_insert_IDLE={do_insert_IDLE}"

    d = (d0) | (d1 << 8) | (d2 << 16) | (d3 << 24)
    dut._log.info("DI0 = {} {} {} {} {:08x} do_insert_IDLE={}".format(d0, d1, d2, d3, d, do_insert_IDLE))
    # if reg change this will break but its a known value we can validate endian against
    # MaxPacketLength=60 AddressWidth == 7
    assert d == 0x303b3007, f"REG_INFO = 0x{d:08x} != 0x303b3007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=52 AddressWidth == 7
    #assert d == 0x30333007, f"REG_INFO = 0x{d:08x} != 0x30333007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=40 AddressWidth == 7
    #assert d == 0x30273007, f"REG_INFO = 0x{d:08x} != 0x30273007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=8 AddressWidth == 6
    #assert d == 0x30073006, f"REG_INFO = 0x{d:08x} != 0x30073006 do_insert_IDLE={do_insert_IDLE}"

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_DISABLE		# EXE_DISABLE
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_RESET			# EXE_RESET
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_ENABLE		# EXE_ENABLE
    await ClockCycles(dut.clk, 1)


    # WBSEL
    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_WBSEL			# EXE_WBSEL
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = (0x05<<4)|EXE_WBSEL	# EXE_WBSEL
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0x5)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_WRITE			# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x5)
        DO_ASSERT(dut.dut.tt2wb.wb_WE, 1)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 1)

    WAIT_FOR_ACK_MAX_CYCLES = 10000
    for i in range(0, WAIT_FOR_ACK_MAX_CYCLES):
        if extract_bit(dut.dut.uio_out.value, ACK_BITID):
            break
        await ClockCycles(dut.clk, 1)
    # We expect some iterations here
    assert i < WAIT_FOR_ACK_MAX_CYCLES, f"TT2WB Timeout waiting for wb_ACK"
        

    # we already clocked it one more to see it (to also see the ACK)
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x0)
        DO_ASSERT(dut.dut.tt2wb.wb_WE, 0)
        DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_RESET			# EXE_RESET (should set 0xf)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)


    #################################################################################
    ## Use DO3
    ##

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    data = 0xcba98765
    dut.uio_in.value = CMD_DO3
    dut.ui_in.value = 0xcb	# DO3
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO3
    dut.ui_in.value = 0xa9	# DO2
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO3
    dut.ui_in.value = 0x87	# DO1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_DO3
    dut.ui_in.value = 0x65	# DO0
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    if not GL_TEST:
        DO_ASSERT(dut.dut.tt2wb.DO, data)
        DO_ASSERT(dut.dut.tt2wb.wb_DAT_MOSI, data)


    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_WRITE		# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    addr = 0xff20		# REG_INFO know return value
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0xff	# AD1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x20	# AD0
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_READ		# EXE_READ
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

    # DI3 use test (these CMD_IDLE insertions are not needed, but validate output hold)
    do_insert_IDLE = bool(random.getrandbits(1))  # False

    dut.uio_in.value = CMD_DI3
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 2)
    else:
        await ClockCycles(dut.clk, 1)	# pipeline setup
    d3 = dut.uo_out.value	# DI3

    dut.uio_in.value = CMD_DI3
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 3)
    d2 = dut.uo_out.value	# DI2

    dut.uio_in.value = CMD_DI3
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 4)
    d1 = dut.uo_out.value	# DI1

    dut.uio_in.value = CMD_DI3
    await ClockCycles(dut.clk, 1)
    if do_insert_IDLE:
        dut.uio_in.value = CMD_IDLE
        await ClockCycles(dut.clk, 5)
    d0 = dut.uo_out.value	# DI0

    d = (d0) | (d1 << 8) | (d2 << 16) | (d3 << 24)
    dut._log.info("DI3 = {} {} {} {} {:08x} do_insert_IDLE={}".format(d0, d1, d2, d3, d, do_insert_IDLE))
    # if reg change this will break but its a known value we can validate endian against
    # MaxPacketLength=60 AddressWidth == 7
    assert d == 0x303b3007, f"REG_INFO = 0x{d:08x} != 0x303b3007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=52 AddressWidth == 7
    #assert d == 0x30333007, f"REG_INFO = 0x{d:08x} != 0x30333007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=40 AddressWidth == 7
    #assert d == 0x30273007, f"REG_INFO = 0x{d:08x} != 0x30273007 do_insert_IDLE={do_insert_IDLE}"
    # MaxPacketLength=8 AddressWidth == 6
    #assert d == 0x30073006, f"REG_INFO = 0x{d:08x} != 0x30073006 do_insert_IDLE={do_insert_IDLE}"

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_WRITE		# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    #################################################################################

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_RESET			# EXE_RESET
    await ClockCycles(dut.clk, 1)


    await ClockCycles(dut.clk, 16)
    #assert False == True, f"DONE"

