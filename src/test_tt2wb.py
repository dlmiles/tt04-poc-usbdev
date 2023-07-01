#
#
#
#  Cocotb helper for the tt03_to_wishbone.v module
#
#
import cocotb
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue


# BinaryValue has Z and X states so need to extract
# FIXME make a version for multiple bits/mask
def extract_bit(v: BinaryValue, bit: int) -> bool:
    assert(bit >= 0)
    if type(v) is BinaryValue:
        s = v.binstr
        if bit+1 > v.n_bits:
            raise Exception(f"{bit+1} > {v.n_bits} from {v}")
        p = s[-(bit+1)]
        #print("extract_bit {} {} {} {} {} p={}".format(v, s, s[-(bit+2)], s[-(bit+1)], s[-(bit)], p))
        return True if(p == '1') else False
    raise Exception(f"type(v) is not BinaryValue: {type(v)}")


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
MAX_ADDRESS = 0x3fff

MAX_CYCLES  = 100000

class TT2WB():
    dut = None
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
        return None

    def save(self):
        # save state
        return None

    def restore(self):
        # restore state
        return None

    def check_address(self, addr: int) -> int:
        assert(addr % 4 == 0), f"TT2WB address {addr} {addr:x} is not modulus 4 aligned"
        assert(addr >= self.MIN_ADDRESS), f"TT2WB address {addr} {addr:x} is out of range, MIN_ADDRESS={self.MIN_ADDRESS}"
        assert(addr <= self.MAX_ADDRESS), f"TT2WB address {addr} {addr:x} is out of range, MAX_ADDRESS={self.MAX_ADDRESS}"
        return addr

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

    async def wait_ack(self, cycles: int = None, can_raise: bool = True) -> bool:
        if cycles is None:
            cycles = self.MAX_CYCLES
        #print("wait_ack cycles={}".format(cycles))
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

    async def exe_enable(self) -> None:
        await self.send(CMD_EXEC, EXE_ENABLE)

    async def exe_disable(self) -> None:
        await self.send(CMD_EXEC, EXE_DISABLE)

    async def exe_read(self, addr: int) -> int:
        addr = self.check_address(addr)
        await self.send(CMD_AD0, addr & 0xff)
        await self.send(CMD_AD1, (addr >> 8) & 0xff)
        await self.send(CMD_EXEC, EXE_READ)
        self.dut._log.debug("WB_READ  0x{:x}".format(addr))

        if not await self.wait_ack():
            return None

        # This is a pipelined sequential read
        # FIXME make this API look more
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

        if d0.is_resolvable and d1.is_resolvable and d2.is_resolvable and d3.is_resolvable:
            data = (d3 << 24) | (d2 << 16) | (d1 << 8) | d0
            self.dut._log.info("WB_READ  0x{:x} = 0x{:x}  b{} {} {} {}".format(addr, data, d3, d2, d1, d0))
            return data
        self.dut._log.info("WB_READ  0x{:x} = b{} {} {} {}".format(addr, d3, d2, d1, d0))
        return None

    async def exe_write(self, addr: int, data: int) -> bool:
        addr = self.check_address(addr)
        await self.send(CMD_AD0, addr & 0xff)
        await self.send(CMD_AD1, (addr >> 8) & 0xff)
        d = data
        for i in range(0, 4):
            await self.send(CMD_DO0, d & 0xff)
            d = d >> 8
        await self.send(CMD_EXEC, EXE_WRITE)
        self.dut._log.debug("WB_WRITE 0x{:x}".format(addr))

        if not await self.wait_ack():
            return False

        self.dut._log.info("WB_WRITE 0x{:x} = 0x{:x}".format(addr, data))
        return True

