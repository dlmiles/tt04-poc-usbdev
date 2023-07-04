#
#
#
#  Cocotb helper for the tt03_to_wishbone.v module
#
#
from typing import Callable
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue

from usbtester import *
from usbtester.cocotbutil import *


# These constants mirror the ones in tt04_to_wishbone.v
CMD_IDLE   = 0x00
CMD_EXEC   = 0x20
CMD_AD0    = 0x40
CMD_AD1    = 0x60
CMD_DO0    = 0x80
CMD_DO3    = 0xa0
CMD_DI0    = 0xc0
CMD_DI3    = 0xe0

EXE_RESET   = 0x01
EXE_DISABLE = 0x04
EXE_ENABLE  = 0x05
EXE_READ    = 0x06
EXE_WRITE   = 0x07

MIN_ADDRESS = 0x0000
MAX_ADDRESS = 0xffff

MAX_CYCLES  = 100000


class TT2WB():
    dut = None
    enable = False
    ADDR_DESC = {}	## TODO
    cmds = {
        CMD_IDLE: "CMD_IDLE",
        CMD_EXEC: "CMD_EXEC",
        CMD_AD0: "CMD_AD0",
        CMD_AD1: "CMD_AD1",
        CMD_DO0: "CMD_DO0",
        CMD_DO3: "CMD_DO3",
        CMD_DI0: "CMD_DI0",
        CMD_DI3: "CMD_DI3"
    }
    exes = {
        EXE_RESET: "EXE_RESET",
        EXE_DISABLE: "EXE_DISABLE",
        EXE_ENABLE: "EXE_ENABLE",
        EXE_READ: "EXE_READ",
        EXE_WRITE: "EXE_WRITE"
    }

    def __init__(self, dut, MIN_ADDRESS=MIN_ADDRESS, MAX_ADDRESS=MAX_ADDRESS, MAX_CYCLES=MAX_CYCLES):
        assert(dut is not None)
        # FIXME check we have signals in dut: dut.uio_in, dut.uio_out, dut.ui_in, dut.uo_out
        self.dut = dut
        self.MIN_ADDRESS = MIN_ADDRESS
        self.MAX_ADDRESS = MAX_ADDRESS
        self.MAX_CYCLES = MAX_CYCLES

        self.enable = False

        return None

    def save(self):
        # save state
        return None

    def restore(self):
        # restore state
        return None

    def addr_desc(self, addr: int, unknown: bool = False) -> str:
        if addr in self.ADDR_DESC:
            return self.ADDR_DESC.get(addr)
        if unknown:
            return None
        return "{:04x}".format(addr)

    def addr_to_bus(self, addr: int) -> int:
        assert addr & ~0xffff == 0, f"addr is {addr:04x} is out of range 16-bit"
        assert addr % 4 == 0, f"addr is {addr:04x} is not modulus 4"
        return addr >> 2

    def addr_translate(self, addr: int) -> int:
        assert addr & ~0x3fff == 0, f"addr is {addr:04x} is out of range 14-bit"
        return addr << 2

    def check_address(self, addr: int) -> int:
        assert(addr % 4 == 0), f"TT2WB address {addr} {addr:04x} is not modulus 4 aligned"
        assert(addr >= self.MIN_ADDRESS), f"TT2WB address {addr} {addr:04x} is out of range, MIN_ADDRESS={self.MIN_ADDRESS}"
        assert(addr <= self.MAX_ADDRESS), f"TT2WB address {addr} {addr:04x} is out of range, MAX_ADDRESS={self.MAX_ADDRESS}"
        return addr

    def check_enable(self) -> None:
        assert(self.enable), f"TT2WB hardware not in enable state for this operation, use tt2wb.exe_enable()"
        return None

    async def send(self, uio_in: int, ui_in: int, save_restore: bool = False) -> None:
        if save_restore:
            self.save()

        self.dut.uio_in.value = uio_in
        self.dut.ui_in.value = ui_in

        await ClockCycles(self.dut.clk, 1)

        if save_restore:
            self.restore()
        return None

    async def recv(self, uio_in: int = None, ui_in: int = None, pipeline: bool = False) -> int:
        if uio_in is not None:
            self.dut.uio_in.value = uio_in
        if ui_in is not None:
            self.dut.ui_in.value = ui_in

        await ClockCycles(self.dut.clk, 1)

        data = self.dut.uo_out.value

        if not pipeline:
            await ClockCycles(self.dut.clk, 1)
        return data

    async def wb_ACK_wait(self, cycles: int = None, can_raise: bool = True) -> bool:
        if cycles is None:
            cycles = self.MAX_CYCLES

        #print("wb_ACK_wait cycles={}".format(cycles))
        for i in range(0, cycles):
            if extract_bit(self.dut.dut.uio_out.value, 4):
                self.dut._log.debug("WB_ACK cycles={} {}".format(i, True))
                return True
            await ClockCycles(self.dut.clk, 1)

        if can_raise:
            raise Exception(f"TT2WB no wb_ACK received after {cycles} cycles")
        return False

    async def idle(self) -> None:
        await self.send(CMD_IDLE, 0)

    async def exe_reset(self) -> None:
        await self.send(CMD_EXEC, EXE_RESET)
        self.enable = False

    async def exe_enable(self) -> None:
        await self.send(CMD_EXEC, EXE_ENABLE)
        self.enable = True

    async def exe_disable(self) -> None:
        await self.send(CMD_EXEC, EXE_DISABLE)
        self.enable = False

    async def exe_read_BinaryValue(self, addr: int) -> tuple:
        self.check_enable()
        addr = self.check_address(addr)
        await self.send(CMD_AD0, self.addr_to_bus(addr) & 0xff)	## FIXME BUS_MASK
        await self.send(CMD_AD1, (self.addr_to_bus(addr) >> 8) & 0xff)
        await self.send(CMD_EXEC, EXE_READ)
        self.dut._log.debug("WB_READ  0x{:04x}".format(addr))

        if not await self.wb_ACK_wait():
            return None

        # This is a pipelined sequential read
        # FIXME make this API look more obvious?
        # This is not obvious but d0 is exposed by default
        # But if we ask for the LSB end after a EXE_READ we get d1 next (not d0)
        d0 = await self.recv(CMD_DI0, pipeline=True)
        #d0 = await self.recv(CMD_DI0, pipeline=True)
        d1 = await self.recv(CMD_DI0, pipeline=True)
        d2 = await self.recv(CMD_DI0, pipeline=True)
        d3 = await self.recv(CMD_IDLE, pipeline=True)

        # This is not obvious but d0 is exposed by default, so there is no
        #  need to issue a command for it, so we issue a command to ask for
        #  the MSB end this saves one cycle for 32bits read
        #d0 = await self.recv(CMD_DI3, pipeline=True)
        #d3 = await self.recv(CMD_DI3, pipeline=True)
        #d2 = await self.recv(CMD_DI3, pipeline=True)
        #d1 = await self.recv(CMD_IDLE, pipeline=True)

        binstr = d3.binstr + d2.binstr + d1.binstr + d0.binstr

        d32 = BinaryValue(binstr, n_bits=32)

        return (d32, d0, d1, d2, d3)


    async def exe_read(self, addr: int, format: Callable[[int,int], str] = None) -> int:
        self.check_enable()
        (d32, d0, d1, d2, d3) = await self.exe_read_BinaryValue(addr)

        if d0.is_resolvable and d1.is_resolvable and d2.is_resolvable and d3.is_resolvable:
            data = (d3 << 24) | (d2 << 16) | (d1 << 8) | d0
            fmtstr = format(data, addr) if(format) else ''
            fmtstr = '' if(fmtstr is None) else fmtstr
            self.dut._log.info("WB_READ  @{} = 0x{:08x}  b{} {} {} {} {}".format(self.addr_desc(addr), data, d3, d2, d1, d0, fmtstr))
            self.reg_dump(addr, data, 'WB_READ ')
            return data

        self.dut._log.info("WB_READ  @{} = b{} {} {} {}  NOT-RESOLVABLE".format(self.addr_desc(addr), d3, d2, d1, d0))
        return None


    async def exe_write(self, addr: int, data: int, format: Callable[[int,int], str] = None) -> bool:
        self.check_enable()
        addr = self.check_address(addr)

        await self.send(CMD_AD0, self.addr_to_bus(addr) & 0xff)
        await self.send(CMD_AD1, (self.addr_to_bus(addr) >> 8) & 0xff)
        d = data
        for i in range(0, 4):
            await self.send(CMD_DO0, d & 0xff)
            d = d >> 8
        await self.send(CMD_EXEC, EXE_WRITE)
        self.dut._log.debug("WB_WRITE {}".format(self.addr_desc(addr)))

        ack = await self.wb_ACK_wait()

        ackstr = '' if(ack is True) else 'NO-WB-ACK'
        fmtstr = format(data, addr) if(format) else ''
        fmtstr = '' if(fmtstr is None) else fmtstr
        self.dut._log.info("WB_WRITE @{} = 0x{:08x} {} {}".format(self.addr_desc(addr), data, ackstr, fmtstr))
        self.reg_dump(addr, data, 'WB_WRITE')
        return ack


    async def wb_read_BinaryValue(self, addr: int) -> tuple:
        return await self.exe_read_BinaryValue(addr)

    async def wb_read(self, addr: int, format: Callable[[int,int], str] = None) -> int:
        return await self.exe_read(addr, format)

    async def wb_write(self, addr: int, data: int, format: Callable[[int,int], str] = None) -> bool:
        return await self.exe_write(addr, data, format)

    def reg_dump(self, addr: int, value: int, pfx: str = '') -> None:
        regname = addr_to_regname(addr)
        if regname:
            regdesc = addr_to_regdesc(addr, value)
            if regdesc:
                self.dut._log.info("{} @{} {:13s} = {}".format(pfx, self.addr_desc(addr), regname, regdesc))

    async def wb_dump(self, addr: int, count: int) -> int:
        self.check_enable()
        addr = self.check_address(addr)
        assert count % 4 == 0, f"count = {count} not aligned to modulus 4"
        offset = 0
        left = count
        while left > 0:
            (d32, d0, d1, d2, d3) = await self.exe_read_BinaryValue(addr)
            s0 = chr(d0) if(d0.is_resolvable and chr(d0.integer).isprintable()) else '.'
            s1 = chr(d1) if(d1.is_resolvable and chr(d1.integer).isprintable()) else '.'
            s2 = chr(d2) if(d2.is_resolvable and chr(d2.integer).isprintable()) else '.'
            s3 = chr(d3) if(d3.is_resolvable and chr(d3.integer).isprintable()) else '.'
            data = "0x{:08x}".format(d32.integer) if(d32.is_resolvable) else '0x????????'
            offstr = "+0x{:04x}".format(offset) if(addr != offset and count > 4) else ''
            regname = addr_to_regname(addr)
            if regname and count == 4:
                offstr = " {:13s}".format(regname)
            self.dut._log.info("WB_DUMP  @{}{} = {}  b{} {} {} {}  {}  {}{}{}{}".format(self.addr_desc(addr), offstr, data, d3, d2, d1, d0, d32, s0, s1, s2, s3))
            if d32.is_resolvable:
                self.reg_dump(addr, d32.integer, 'WB_DUMP ')
            left -= 4
            addr += 4
            offset += 4
        return count


__all__ = [
    'TT2WB'
]
