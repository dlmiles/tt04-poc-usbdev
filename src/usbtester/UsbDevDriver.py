#
#
#
#  SpinalHDL UsbDevice bus transaction helper
#
#
import os
from cocotb.triggers import ClockCycles

from usbtester import *
from .cocotbutil import *


class UsbDevDriver():
    dut = None
    bus = None

    def __init__(self, dut, bus):
        assert(dut is not None)
        assert(bus is not None)
        self.dut = dut
        self.bus = bus
        return None


    async def halt(self, endp: int, can_raise: bool = True) -> bool:
        assert endp & ~0xf == 0, f"endp is not valid {endp} for a 4-bit value"

        await self.bus.wb_write(REG_HALT, reg_halt(endp=endp, enable=True), regdesc)
        DELAY = 16

        rv = False
        # wait for effective enable bit set ? after issuing enable=True
        for i in range(0, 256):
            data = await self.bus.wb_read(REG_HALT, regdesc)
            if extract_bit(data, 5):	# effective_enable is bit5
                rv = True
                break
            await ClockCycles(dut.clk, DELAY)
        
        if not rv and can_raise:
            raise Exception("halt failed for endp={} after {} cycles".format(endp, i*DELAY))
        if i > 0:
            self.dut._log.info("halt(endp={}) took {} cycles".format(endp, i*DELAY))
        return rv


    async def unhalt(self, endp: int) -> bool:
        assert endp & ~0xf == 0, f"endp is not valid {endp} for a 4-bit value"

        await self.bus.wb_write(REG_HALT, reg_halt(endp=endp, enable=False), regdesc)

        return True


    async def setup(self) -> None:
        # role call on registers
        data = await self.bus.wb_read(REG_FRAME)

        data = await self.bus.wb_read(REG_ADDRESS)

        data = await self.bus.wb_read(REG_INTERRUPT)

        data = await self.bus.wb_read(REG_HALT)

        data = await self.bus.wb_read(REG_CONFIG)

        data = await self.bus.wb_read(REG_INFO)


        await self.bus.wb_dump(REG_EP0, BUF_END)


        await self.bus.wb_write(REG_ADDRESS, reg_address(address=0, enable=False, trigger=False))

        # ENDPOINT#0
        await self.halt(endp=0)	# HALT EP=0

        buf_ep0_desc = BUF_DESC0
        buf_ep0_length = 20
        buf_ep0_eod = buf_ep0_desc + 12 + buf_ep0_length
        await self.bus.wb_write(buf_ep0_desc+0, 0x000f0000)	# code=INPROGRESS
        await self.bus.wb_write(buf_ep0_desc+4, 0x00140000)	# length=20
        await self.bus.wb_write(buf_ep0_desc+8, 0x00030000)	# dir=IN, interrupt=true
        await self.bus.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(buf_ep0_desc), max_packet_size=buf_ep0_length)) #

        await self.unhalt(endp=0)


        # ENDPOINT#1
        await self.halt(endp=1) # HALT EP=1

        buf_ep1_desc = BUF_DESC0 + 12 + 20  # 0x0040
        buf_ep1_length = 8
        buf_ep1_eod = buf_ep1_desc + 12 + buf_ep1_length
        assert buf_ep1_eod <= BUF_END, f"EP1 configuration puts end-of-data beyond end-of-buffer ({buf_ep1_eod} > {BUF_END})"
        await self.bus.wb_write(buf_ep1_desc+0, desc0(code=DESC0_INPROGRESS))
        await self.bus.wb_write(buf_ep1_desc+4, desc1(length=buf_ep1_length))  # length=8
        await self.bus.wb_write(buf_ep1_desc+8, desc2(direction=DESC2_IN, interrupt=True))  # dir=IN, interrupt=true
        await self.bus.wb_write(REG_EP1, reg_endp(enable=True, head=addr_to_head(buf_ep1_desc), max_packet_size=buf_ep1_length)) #
        await self.unhalt(endp=0)


        # ENDPOINT#2
        await self.halt(endp=2) # HALT EP=2

        # ENDPOINT#3
        await self.halt(endp=3) # HALT EP=3


        data = await self.bus.wb_read(REG_INTERRUPT)
        assert data == 0, f"REG_INTERRUPT expecting it to be clear already"
        # CLEAR INTERRUPTS (just before we enable them)
        await self.bus.wb_write(REG_INTERRUPT, reg_interrupt(all=True))


        # FIXME confirm this is a good power-on default electrically, it feels better to float until the driver actives
        # before pullup it set, check the output is 
        assert self.dut.dut.usb_dp_writeEnable,    f"self.dut.dut.usb_dp_writeEnable = {str(self.dut.dut.usb_dp_writeEnable.value)}"
        assert self.dut.dut.usb_dp_write == False, f"self.dut.dut.usb_dp_write = {str(self.dut.dut.usb_dp_write.value)}"

        assert self.dut.dut.usb_dm_writeEnable,    f"self.dut.dut.usb_dm_writeEnable = {str(self.dut.dut.usb_dm_writeEnable.value)}"
        assert self.dut.dut.usb_dm_write == False, f"self.dut.dut.usb_dm_write = {str(self.dut.dut.usb_dm_write.value)}"

        # ENABLE INTERRUPTS (and activate line state)
        await self.bus.wb_write(REG_CONFIG, reg_config(interrupt_enable_set=True, pullup_set=True)) # FIXME is this HS=True?

        await ClockCycles(self.dut.clk, 28+4)	# need some ticks to observe update (clock-domain-crossing and back)

        assert self.dut.dut.usb_dp_writeEnable == False,               f"self.dut.dut.usb_dp_writeEnable = {str(self.dut.dut.usb_dp_writeEnable.value)}"
        assert self.dut.dut.usb_dp_write.value.is_resolvable == False, f"self.dut.dut.usb_dp_write = {str(self.dut.dut.usb_dp_write.value)}"

        assert self.dut.dut.usb_dm_writeEnable == False, f"self.dut.dut.usb_dm_writeEnable = {str(self.dut.dut.usb_dm_writeEnable.value)}"
        assert self.dut.dut.usb_dm_write.value.is_resolvable == False,   f"self.dut.dut.usb_dm_write = {str(self.dut.dut.usb_dm_write.value)}"



    async def wait_for_interrupt(self, cycles: int = None) -> int:
        if cycles is None:
            cycles = 1000000

        for i in range(0, cycles):
            while self.dut.interrupt.value == 0:
                await ClockCycles(self.dut.clk, 1)

        if self.dut.interrupt.value == 0:
            return None

        value = await self.bus.wb_read(REG_INTERRUPT)
        s = dump_reg_interrupt(value)
        self.dut._log.info("{}".format(s))

        return value


__all__ = [
    'UsbDevDriver'
]
