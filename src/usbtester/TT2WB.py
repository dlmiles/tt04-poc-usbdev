#
#
#
#  Cocotb helper for the tt04_to_wishbone.v module
#
#
from typing import Callable
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue

from usbtester import *
from usbtester.cocotbutil import *
from .Payload import *


# These constants mirror the ones in tt04_to_wishbone.v
CMD_IDLE   = 0x00
CMD_EXEC   = 0x20
CMD_AD0    = 0x40
CMD_AD1    = 0x60
CMD_DO0    = 0x80	# master data out (towards tt_um module)
CMD_DO3    = 0xa0
CMD_DI0    = 0xc0	# master data in (away from tt_um module)
CMD_DI3    = 0xe0
CMD_MASK   = 0xe0	# bit5..7 all set

EXE_RESET   = 0x01
EXE_WBSEL   = 0x02
EXE_DISABLE = 0x04
EXE_ENABLE  = 0x05
EXE_READ    = 0x06
EXE_WRITE   = 0x07
EXE_MASK    = 0x07

ACK_BITID = 4

MIN_ADDRESS = 0x0000
MAX_ADDRESS = 0xffff

# CONFIGURATION: Everything should derive from these two values:
ADR_WIDTH = 16
ADR_BUS_WIDTH = 14

ADR_SHIFT_COUNT = ADR_WIDTH - ADR_BUS_WIDTH # 2
assert ADR_SHIFT_COUNT >= 0
ADR_ALIGN_WIDTH = 2**ADR_SHIFT_COUNT # 4
ADR_MASK = (2**ADR_WIDTH)-1 # 0xffff
ADR_ZERO_MASK = (2**ADR_SHIFT_COUNT)-1 # 0x0003
ADR_USED_MASK = ADR_MASK & ~ADR_ZERO_MASK # 0xfffc
ADR_SHIFTED_MASK = ADR_USED_MASK >> ADR_SHIFT_COUNT # 0x3fff

MAX_CYCLES  = 100000


# Too lazy to validate other scenarios
assert ADR_SHIFT_COUNT == 2
assert ADR_ALIGN_WIDTH == 4
assert ADR_MASK == 0xffff
assert ADR_ZERO_MASK == 0x0003
assert ADR_USED_MASK == 0xfffc
assert ADR_SHIFTED_MASK == 0x3fff


class TT2WB():
    UIO_IN_MASK = 0xe0	# bit7..bit5 are input, bit4 output, bit3..bit0 unused
    ADDR_DESC = {
        # Here you can create a dict name for address location to help diagnostics in logs
        # There is also the 'format' Callable mechanism
        #0x0000: "ADDR0000"
    }
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
        EXE_WBSEL: "EXE_WBSEL",
        EXE_DISABLE: "EXE_DISABLE",
        EXE_ENABLE: "EXE_ENABLE",
        EXE_READ: "EXE_READ",
        EXE_WRITE: "EXE_WRITE"
    }

    def __init__(self, dut, MIN_ADDRESS: int = MIN_ADDRESS, MAX_ADDRESS: int = MAX_ADDRESS, MAX_CYCLES: int = MAX_CYCLES):
        assert(dut is not None)
        # FIXME check we have signals in dut: dut.uio_in, dut.uio_out, dut.ui_in, dut.uo_out
        self._dut = dut
        self.MIN_ADDRESS = MIN_ADDRESS
        self.MAX_ADDRESS = MAX_ADDRESS
        self.MAX_CYCLES = MAX_CYCLES

        self._enable = False
        self._need_issue = False
        self._force_default = False
        self._addr = None
        self._data = None

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
        assert addr & ~ADR_MASK == 0, f"addr is {addr:04x} is out of range {ADR_WIDTH}-bit"
        assert addr % ADR_ALIGN_WIDTH == 0, f"addr is {addr:04x} is not modulus {ADR_ALIGN_WIDTH}"
        return addr >> ADR_SHIFT_COUNT

    def addr_translate(self, busaddr: int) -> int:
        assert busaddr & ~ADR_SHIFTED_MASK == 0, f"addr is {busaddr:04x} is out of range {ADR_BUS_WIDTH}-bit"
        return busaddr << ADR_SHIFT_COUNT

    def check_address(self, addr: int) -> None:
        assert addr is not None, f"TT2WB address = {addr}"
        assert addr % ADR_ALIGN_WIDTH == 0, f"TT2WB address {addr} {addr:04x} is not modulus {ADR_ALIGN_WIDTH} aligned"
        assert addr >= self.MIN_ADDRESS, f"TT2WB address {addr} {addr:04x} is out of range, MIN_ADDRESS={self.MIN_ADDRESS}"
        assert addr <= self.MAX_ADDRESS, f"TT2WB address {addr} {addr:04x} is out of range, MAX_ADDRESS={self.MAX_ADDRESS}"

    def check_enable(self) -> None:
        assert self._enable, f"TT2WB hardware not in enable state for this operation, use tt2wb.exe_enable()"
        return None

    def addr_align(self, addr: int) -> int:
        return addr & ADR_USED_MASK

    def resolve_addr(self, addr: int = None) -> int:
        if addr is None:
            addr = self._addr
        assert addr is not None, f"TT2WB addr = {addr}"
        return addr

    def resolve_data(self, data: int = None) -> int:
        if data is None:
            data = self._data
        assert data is not None, f"TT2WB data = {data}"
        return data

    def update_need_issue(self, uio_in: int, ui_in: int) -> bool:
        if uio_in is not None and ui_in is not None:
            cmd = uio_in & CMD_MASK
            exe = ui_in & EXE_MASK
            newval = cmd == CMD_EXEC and (exe == EXE_READ or exe == EXE_WRITE)
            self._need_issue = newval
        return self._need_issue

    async def send(self, uio_in: int, ui_in: int, save_restore: bool = False) -> None:
        if save_restore:
            self.save()

        self._dut.uio_in.value = (self._dut.uio_in.value & ~self.UIO_IN_MASK) | uio_in
        self._dut.ui_in.value = ui_in

        await ClockCycles(self._dut.clk, 1)

        if save_restore:
            self.restore()

        self.update_need_issue(uio_in, ui_in)

        return None

    async def recv(self, uio_in: int = None, ui_in: int = None, pipeline: bool = False) -> int:
        if uio_in is not None:
            self._dut.uio_in.value = (self._dut.uio_in.value & ~self.UIO_IN_MASK) | uio_in
        if ui_in is not None:
            self._dut.ui_in.value = ui_in

        await ClockCycles(self._dut.clk, 1)

        data = self._dut.uo_out.value

        if not pipeline:
            await ClockCycles(self._dut.clk, 1)

        self.update_need_issue(uio_in, ui_in)

        return data

    def is_ack(self) -> bool:
        return extract_bit(self._dut.uio_out.value, ACK_BITID)

    async def wb_ACK_wait(self, cycles: int = None, can_raise: bool = True) -> bool:
        if cycles is None:
            cycles = self.MAX_CYCLES

        if cycles == 0 and self.is_ack():
            return True

        #print("wb_ACK_wait cycles={}".format(cycles))
        for i in range(cycles):
            if self.is_ack():
                self._dut._log.debug("WB_ACK cycles={} {}".format(i, True))
                return True
            await ClockCycles(self._dut.clk, 1)

        if can_raise:
            raise Exception(f"TT2WB no wb_ACK received after {cycles} cycles")
        return False

    async def exe_idle(self) -> None:
        await self.send(CMD_IDLE, 0)

    async def exe_reset(self) -> None:
        await self.send(CMD_EXEC, EXE_RESET)
        self._enable = False

    async def exe_wbsel(self, sel: int = 0xf) -> None:
        # FIXME we can track the last wbsel to mitigate unnecessary changes
        assert sel & ~0xf == 0, f"sel = 0x{sel:x} is not inside valid 4-bit range"
        await self.send(CMD_EXEC, (sel << 4) | EXE_WBSEL)

    async def exe_enable(self) -> None:
        await self.send(CMD_EXEC, EXE_ENABLE)
        self._enable = True

    async def exe_disable(self) -> None:
        await self.send(CMD_EXEC, EXE_DISABLE)
        self._enable = False

    async def cmd_addr(self, addr: int, force: bool = False) -> bool:
        self.check_address(addr)
        # If the internal ADR state is already setup to 'addr' then we can
        #  suppress using he cycles to send instruction to change it
        if force or self._addr is None or self._addr != addr:
            await self.send(CMD_AD0, addr & 0xff)
            await self.send(CMD_AD1, (addr >> 8) & 0xff)
            self._addr = addr
            return True

        return False

    async def cmd_data(self, data: int, force: bool = False) -> bool:
        assert data is not None, f"data = {data}"
        if force or self._data is None or self._data != data:
            d = data
            for i in range(4):
                # FIXME This assumes the last command wasn't a CMD_DO0, needs detection and assert
                # caller can use exe_enable() before ?
                await self.send(CMD_DO0, d & 0xff)
                d = d >> 8
            self._data = data
            return True

        return False

    async def exe_read_BinaryValue(self, addr: int = None) -> tuple:
        self.check_enable()

        if addr is not None:
            await self.cmd_addr(addr, self._force_default)
        addr = self.resolve_addr(addr)

        if self._need_issue:	# insert extra CMD to reset issue=0 in tt2wb hardware
            #print("exe_read_BinaryValue({}) need_issue={} invoking send(CMD_EXEC, EXE_ENABLE)".format(addr, self._need_issue))
            await self.send(CMD_EXEC, EXE_ENABLE)

        await self.send(CMD_EXEC, EXE_READ)
        self._dut._log.debug("WB_READ  @0x{:04x}".format(addr))

        if not await self.wb_ACK_wait():
            # need_issue mechanism takes care with deferring the reset of issue=0
            return None

        # This is a pipelined sequential read
        # FIXME make this API look more obvious?
        # This is not obvious but d0 is exposed by default (so we can read it immediately)
        # But if we ask for the LSB end after the EXE_READ we get d1 next (not d0)
        d0 = await self.recv(CMD_DI0, pipeline=True)
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


    async def exe_read(self, addr: int = None, format: Callable[[int,int], str] = None) -> int:
        self.check_enable()

        (d32, d0, d1, d2, d3) = await self.exe_read_BinaryValue(addr)

        addr = self.resolve_addr(addr)

        if d0.is_resolvable and d1.is_resolvable and d2.is_resolvable and d3.is_resolvable:
            data = (d3 << 24) | (d2 << 16) | (d1 << 8) | d0
            fmtstr = format(data, addr) if(format) else ''
            fmtstr = '' if(fmtstr is None) else fmtstr
            self._dut._log.info("WB_READ  @{} = 0x{:08x}  b{} {} {} {} {}".format(self.addr_desc(addr), data, d3, d2, d1, d0, fmtstr))
            self.reg_dump(addr, data, 'WB_READ ')
            return data

        self._dut._log.info("WB_READ  @{} = b{} {} {} {}  NOT-RESOLVABLE".format(self.addr_desc(addr), d3, d2, d1, d0))
        return None


    async def exe_write(self, data: int = None, addr: int = None, format: Callable[[int,int], str] = None, wait_ack: bool = True) -> bool:
        self.check_enable()

        if addr is not None:
            await self.cmd_addr(addr, self._force_default)
        addr = self.resolve_addr(addr)

        if data is not None:
            await self.cmd_data(data, self._force_default)
        data = self.resolve_data(data)

        if self._need_issue:	# insert extra CMD to reset issue=0 in tt2wb hardware
            #print("exe_write(data={}, addr={}) need_issue={} invoking send(CMD_EXEC, EXE_ENABLE)".format(data, addr, self._need_issue))
            await self.send(CMD_EXEC, EXE_ENABLE)

        await self.send(CMD_EXEC, EXE_WRITE)
        self._dut._log.debug("WB_WRITE {}".format(self.addr_desc(addr)))

        if wait_ack:
            ack = await self.wb_ACK_wait() 	# will raise exception on timeout
            ackstr = '' if(ack is True) else 'NO-WB-ACK'
        else:
            ack = None
            ackstr = 'NO-WAIT-ACK'

        fmtstr = format(data, addr) if(format) else ''
        fmtstr = '' if(fmtstr is None) else fmtstr
        self._dut._log.info("WB_WRITE @{} = 0x{:08x} {} {}".format(self.addr_desc(addr), data, ackstr, fmtstr))
        self.reg_dump(addr, data, 'WB_WRITE')
        return ack


    async def wb_read_BinaryValue(self, addr: int = None) -> tuple:
        return await self.exe_read_BinaryValue(addr)

    async def wb_read(self, addr: int = None, format: Callable[[int,int], str] = None) -> int:
        return await self.exe_read(addr, format)

    async def wb_read_payload(self, addr: int = None, count: int = 0, format: Callable[[int,int], str] = None) -> Payload:
        assert count % 4 == 0

        ba = bytearray()
        raddr = addr
        left = count
        while left > 0:
            assert left >= 4

            data = await self.wb_read(raddr, format)

            ba.extend([
                (data      ) & 0xff,
                (data >>  8) & 0xff,
                (data >> 16) & 0xff,
                (data >> 24) & 0xff
            ])
            left -= 4
            raddr += 4

        return Payload(ba)

    # FIXME change argument order  data, addr, format
    async def wb_write(self, addr: int, data: int, format: Callable[[int,int], str] = None) -> bool:
        return await self.exe_write(data, addr, format)

    async def wb_write_payload(self, addr: int, payload: Payload, write_size: int = 4, last_write_size: int = 4) -> int:
        assert payload is not None
        assert write_size == 4		# write size bytes
        assert last_write_size == 4	# end of buffer
        ## FIXME the goal here was to allow 8/16/32bit writes (write_size),
        ##    but also allow the last write (last_write_size) to be a smaller value
        ##    using wb_WBSEL to setup partial writes
        assert len(payload) % write_size == 0, f"{len(payload)} % {write_size} == 0"
        assert len(payload) % last_write_size == 0, f"{len(payload)} % {last_write_size} == 0"

        iter = payload.__iter__()	# byte iterator

        waddr = addr
        while iter.has_more():
            i = 0
            v = 0
            while i < write_size:
                b = iter.next_or_default()
                if b is None:
                    break
                v = v << 8 | b
                i += 1

            if i == 0:
                break

            if iter.has_more():
                assert write_size == i		## more to go
            else:
                assert last_write_size == i	## last one

            if i != 4:
                wbsel = (1 << 4) - 1	# produces mask 1=1 2=3 3=7 5=15
                self.exe_wbsel(wbsel)

            await self.wb_write(waddr, v)
            waddr += i

            if i != 4:
                self.exe_wbsel()		# reset

        return waddr - addr	# count

    def reg_dump(self, addr: int, value: int, pfx: str = '') -> None:
        self.check_address(addr)
        regname = addr_to_regname(addr)
        if regname:
            regdesc = addr_to_regdesc(addr, value)
            if regdesc:
                self._dut._log.info("{} @{} {:13s} = {}".format(pfx, self.addr_desc(addr), regname, regdesc))

    async def wb_dump(self, addr: int, count: int) -> int:
        self.check_enable()
        self.check_address(addr)

        assert count % ADR_ALIGN_WIDTH == 0, f"count = {count} not aligned to modulus {ADR_ALIGN_WIDTH}"
        offset = 0
        left = count
        while left > 0:
            (d32, d0, d1, d2, d3) = await self.exe_read_BinaryValue(addr)
            s0 = chr(d0) if(d0.is_resolvable and chr(d0.integer).isprintable()) else '.'
            s1 = chr(d1) if(d1.is_resolvable and chr(d1.integer).isprintable()) else '.'
            s2 = chr(d2) if(d2.is_resolvable and chr(d2.integer).isprintable()) else '.'
            s3 = chr(d3) if(d3.is_resolvable and chr(d3.integer).isprintable()) else '.'
            data = "0x{:08x}".format(d32.integer) if(d32.is_resolvable) else '0x????????'
            offstr = "+0x{:04x}".format(offset) if(addr != offset and count > ADR_ALIGN_WIDTH) else ''
            regname = addr_to_regname(addr)
            if regname and count == ADR_ALIGN_WIDTH:
                offstr = " {:13s}".format(regname)
            self._dut._log.info("WB_DUMP  @{}{} = {}  b{} {} {} {}  {}  {}{}{}{}".format(self.addr_desc(addr), offstr, data, d3, d2, d1, d0, d32, s0, s1, s2, s3))
            if d32.is_resolvable:
                self.reg_dump(addr, d32.integer, 'WB_DUMP ')
            left -= ADR_ALIGN_WIDTH
            addr += ADR_ALIGN_WIDTH
            offset += ADR_ALIGN_WIDTH
        return count


__all__ = [
    'TT2WB'
]
