#
#
#
#
#
#
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue
from usbtester.cocotbutil import *
from usbtester.TT2WB import TT2WB, ADR_MASK, CMD_IDLE, CMD_EXEC, CMD_AD0, CMD_AD1, CMD_DO0, CMD_DO3, CMD_DI0, CMD_DI3, EXE_RESET, EXE_WBSEL, EXE_DISABLE, EXE_ENABLE, EXE_READ, EXE_WRITE, ACK_BITID


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
    # Ideally we could do with the stacktrace returned being the callers (not here)
    assert(signal.value, expected), format_assert(signal, expected)


async def test_tt2wb_cooked(dut):
    tt2wb = TT2WB(dut)

    await tt2wb.exe_reset()

    DO_ASSERT(dut.dut.tt2wb.ADR.value, 0)
    DO_ASSERT(dut.dut.tt2wb.DO.value, 0)
    DO_ASSERT(dut.dut.tt2wb.DI.value, 0)
    DO_ASSERT(dut.dut.tt2wb.SEL.value, 0xf)
    DO_ASSERT(dut.dut.tt2wb.CYC.value, 0)
    DO_ASSERT(dut.dut.tt2wb.STB.value, 0)
    DO_ASSERT(dut.dut.tt2wb.WE.value, 0)

    dut.uio_in.value = 0x00
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)

    await tt2wb.exe_enable()

    DO_ASSERT(dut.dut.tt2wb.CYC.value, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_CYC.value, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_STB.value, 0)


    addr = 0xfedc		# (addr is 14bit, addr_to_bus(0xfedc) = 0x3fb7)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0xba98		# (addr is 14bit, addr_to_bus(0xba98) = 0x2ea6)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0x3210		# (addr is 14bit, addr_to_bus(0x3210) = 0x0c84)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0x7654		# (addr is 14bit, addr_to_bus(0x7654) = 0x1d95)
    await tt2wb.cmd_addr(addr)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    data = 0xfedcba98
    ack = await tt2wb.exe_write(data)
    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.DO.value, addr)
    DO_ASSERT(dut.dut.tt2wb.wb_DAT_MOSI.value, addr)

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


    await tt2wb.exe_wbsel(0)		# WBSEL

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.SEL, 0)

    await tt2wb.exe_wbsel(0x5)		# WBSEL

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.SEL, 0x5)

    ack = await tt2wb.exe_write()	# WRITE (with wb_SEL=0x5)

    await ClockCycles(dut.clk, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x5)
    DO_ASSERT(dut.dut.tt2wb.wb_WE, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_STB, 1)

    assert ack, f"wb_ACK = {ack}"

    # we already clocked it one more to see it (to also see the ACK)
    DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x0)
    DO_ASSERT(dut.dut.tt2wb.wb_WE, 0)
    DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    await tt2wb.exe_reset()		# EXE_RESET (should set 0xf)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)


    await ClockCycles(dut.clk, 16)
    #assert False, f"STOP"


# testing tt04_to_wishbone.v
async def test_tt2wb_raw(dut):
    tt2wb = TT2WB(dut)

    # The raw version of the test
    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_RESET		# EXE_RESET
    await ClockCycles(dut.clk, 1)

    DO_ASSERT(dut.dut.tt2wb.ADR.value, 0)
    DO_ASSERT(dut.dut.tt2wb.DO.value, 0)
    DO_ASSERT(dut.dut.tt2wb.DI.value, 0)
    DO_ASSERT(dut.dut.tt2wb.SEL.value, 0xf)
    DO_ASSERT(dut.dut.tt2wb.CYC.value, 0)
    DO_ASSERT(dut.dut.tt2wb.STB.value, 0)
    DO_ASSERT(dut.dut.tt2wb.WE.value, 0)

    #while dut.dut.wb_ACK.value == 0:
    #    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x00
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)


    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_ENABLE	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    DO_ASSERT(dut.dut.tt2wb.CYC.value, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_CYC.value, 1)
    DO_ASSERT(dut.dut.tt2wb.wb_STB.value, 0)


    addr = 0xfedc		# (addr is 14bit, addr_to_bus(0xfedc) = 0x3fb7)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0xdc	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0xfe	# AD1
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0xba98		# (addr is 14bit, addr_to_bus(0xba98) = 0x2ea6)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0x98	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0xba	# AD0 (double, into high-half)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0x3210		# (addr is 14bit, addr_to_bus(0x3210) = 0x0c84)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x32	# AD1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x10	# AD1 (double, into low-half)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


    addr = 0x7654		# (addr is 14bit, addr_to_bus(0x7654) = 0x1d95)
    dut.uio_in.value = CMD_AD0
    dut.ui_in.value = 0x54	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = CMD_AD1
    dut.ui_in.value = 0x76	# AD1
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.ADR.value, addr)
    expected = tt2wb.addr_to_bus(addr)
    DO_ASSERT(dut.dut.tt2wb.wb_ADR.value, expected)


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
    DO_ASSERT(dut.dut.tt2wb.DO.value, addr)
    DO_ASSERT(dut.dut.tt2wb.wb_DAT_MOSI.value, addr)


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

    dut.uio_in.value = CMD_EXEC		# EXEC
    dut.ui_in.value = EXE_READ		# EXE_READ
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, ACK_BITID):
        await ClockCycles(dut.clk, 1)

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
    DO_ASSERT(dut.dut.tt2wb.SEL, 0)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = (0x05<<4)|EXE_WBSEL	# EXE_WBSEL
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.SEL, 0x5)

    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_WRITE			# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)
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
    DO_ASSERT(dut.dut.tt2wb.wb_SEL, 0x0)
    DO_ASSERT(dut.dut.tt2wb.wb_WE, 0)
    DO_ASSERT(dut.dut.tt2wb.wb_STB, 0)


    dut.uio_in.value = CMD_EXEC			# EXEC
    dut.ui_in.value = EXE_RESET			# EXE_RESET (should set 0xf)
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)	# clock it one more to see it
    DO_ASSERT(dut.dut.tt2wb.SEL, 0xf)


    await ClockCycles(dut.clk, 16)
    #assert False == True, f"DONE"

