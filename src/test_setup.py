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

BUF_END = 0x0048

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



def build_endp(
        enable: bool = False,
        stall: bool = False,
        nack: bool = False,
        data_phase_n: bool = False, # this appears to have inverted meaning
        head: int = 0, # 16byte units
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
    if data_phase_n:
        val |= 0x00008	# bit3
    assert head & ~0xfff == 0, f"head out of range {head}"
    val |= (head & 0xfff) << 4	# bit4..15 (12bits)
    if isochronous:
        val |= 0x10000   # bit16
    assert max_packet_size & ~0x3ff == 0, f"max_packet_size out of range {max_packet_size}"
    val |= (max_packet_size & 0x3ff) << 22 # bit22..31 (10bits)
    return val


def build_interrupt(
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


def build_halt(
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


class USBDEV():
    dut = None
    bus = None

    def __init__(self, dut, bus):
        assert(dut is not None)
        assert(bus is not None)
        self.dut = dut
        self.bus = bus
        return None


    async def setup(self) -> None:
        # role call on registers
        data = await self.bus.wb_read(REG_FRAME)

        data = await self.bus.wb_read(REG_ADDRESS)

        data = await self.bus.wb_read(REG_INTERRUPT)

        data = await self.bus.wb_read(REG_HALT)

        data = await self.bus.wb_read(REG_CONFIG)

        data = await self.bus.wb_read(REG_INFO)


        await self.bus.wb_dump(BUF_EP0, BUF_END)


        # ENDPOINT#0
        await self.bus.wb_write(REG_HALT, build_halt(endp=0)) # HALT EP=0

        # Not needed but we do it to peek at state
        data = await self.bus.wb_read(REG_HALT)

        await self.bus.wb_write(BUF_DESC0, 0x00ff0000)	# code=INPROGRESS
        await self.bus.wb_write(BUF_DESC1, 0x00140000)	# length=20
        await self.bus.wb_write(BUF_DESC2, 0x00030000)	# dir=IN, interrupt=true
        await self.bus.wb_write(BUF_EP0, build_endp(enable=True, data_phase_n=True, head=1, max_packet_size=20)) #

        await self.bus.wb_write(REG_HALT, build_halt(endp=0, enable=True)) # HALT EP=0 (unhalt)


        # ENDPOINT#1
        await self.bus.wb_write(REG_HALT, build_halt(endp=1)) # HALT EP=1

        # Not needed but we do it to peek at state
        data = await self.bus.wb_read(REG_HALT)

        await self.bus.wb_write(0x0030, 0x00ff0000)  # code=INPROGRESS
        await self.bus.wb_write(0x0034, 0x00080000)  # length=8
        await self.bus.wb_write(0x0038, 0x00030000)  # dir=IN, interrupt=true
        await self.bus.wb_write(BUF_EP1, build_endp(enable=True, data_phase_n=True, head=3, max_packet_size=8)) #

        await self.bus.wb_write(REG_HALT, build_halt(endp=1, enable=True)) # HALT EP=1 (unhalt)


        # CLEAR INTERRUPTS
        await self.bus.wb_write(REG_INTERRUPT, build_interrupt(all=True))


        # ENABLE INTERRUPTS
        await self.bus.wb_write(REG_CONFIG, build_config(interrupt_enable_set=True, pullup_set=True))



    async def wait_for_interrupt(self, cycles: int = None) -> int:
        if cycles is None:
            cycles = 1000000

        for i in range(0, cycles):
            while self.dut.interrupt.value == 0:
                await ClockCycle(self.dut.clk, 1)

        if self.dut.interrupt.value == 0:
            return None

        value = await self.bus.wb_read(REG_INTERRUPT)
        s = dump_reg_interrupt(value)
        self.dut._log.info("{}".format(s))

        return value

