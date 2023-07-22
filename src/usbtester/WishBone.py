#
#
#
#
#
#


class WishBone():
    MAX_CYCLES = 100000
    MIN_ADDRESS = 0x0000
    MAX_ADDRESS = 0xffff

    def __init__(self, dut):
        assert(dut is not None)
        self._dut = dut
        self._enable = False
        return None


    def addr_desc(self, addr: int, unknown: bool = False) -> str:
        if addr in ADDR_DESC:
            return ADDR_DESC.get(addr)
        if unknown:
            return None
        return "{:04x}".format(addr)

    def addr_to_bus(self, addr: int) -> int:
        return addr >> 2

    def addr_translate(self, addr: int) -> int:
        return addr << 2

    def check_address(self, addr: int) -> int:
        assert(addr % 4 == 0), f"TT2WB address {addr} {addr:04x} is not modulus 4 aligned"
        assert(addr >= self.MIN_ADDRESS), f"TT2WB address {addr} {addr:04x} is out of range, MIN_ADDRESS={self.MIN_ADDRESS}"
        assert(addr <= self.MAX_ADDRESS), f"TT2WB address {addr} {addr:04x} is out of range, MAX_ADDRESS={self.MAX_ADDRESS}"
        return addr

    async def wb_ACK_wait(self, cycles: int = None, can_raise: bool = True) -> bool:
        if cycles is None:
            cycles = self.MAX_CYCLES

        for i in range(0, cycles):
            while dut.dut.wb_ACK.value == 0:
                self._dut._log.debug("WB_ACK cycles={} {}".format(i, True))
                return True
            await ClockCycle(self._dut.clk, 1)

        if can_raise:
            raise Exception(f"WishBone no wb_ACK received after {cycles} cycles")
        return dut.dut.wb_ACK.value == 1

    async def wb_enable(self) -> None:
        self._dut.wb_CYC.value = 1
        self._enable = False

    async def wb_disable(self) -> None:
        self._dut.wb_CYC.value = 0
        self._enable = False

    async def wb_write(self, addr: int, data: int) -> bool:
        self.check_enable()
        addr = self.check_address(addr)

        dut.wb_STB.value = 1
        dut.wb_WE.value = 1
        dut.wb_SEL.value = 0xf	# 4 bits (32bit write)
        dut.wb_ADR.value = self.addr_to_bus(addr)
        dut.wb_DAT_MOSI.value = data
        await ClockCycle(dut.clk, 1)
        dut._log.debug("WB_WRITE {}", self.addr_desc(addr))

        ack = await self.wb_ACK_wait()

        dut.wb_STB.value = 0
        dut.wb_WE.value = 0
        dut.wb_SEL.value = 0

        ackstr = '' if(ack is True) else 'NO-WB-ACK'
        dut._log.info("WB_WRITE @{} = 0x{:08x} {}", self.addr_desc(addr), data, ackstr)
        return ack


    async def wb_read(self, addr: int) -> int:
        self.check_enable()
        addr = self.check_address(addr)

        self._dut.wb_STB.value = 1
        self._dut.wb_WE.value = 0
        self._dut.wb_ADR.value = self.addr_to_bus(addr)

        # FIXME async this with timeout/iteration limit
        await self.wb_ACK_wait()
        #while dut.dut.wb_ACK.value == 0:
        #    await ClockCycle(dut.clk, 1)

        data = self._dut.wb_DAT_MISO.value

        binstr = data.binstr
        (d32, d0, d1, d2, d3) = retval, BinaryValue(binstr[0:8]), BinaryValue(binstr[8:16]), BinaryValue(binstr[16:24]), BinaryValue(binstr[24:32])

        self._dut.wb_STB.value = 0

        if data.is_resolvable:
            dut._log.info("WB_READ  @{} = 0x{:08x}  b{} {} {} {}", self.addr_desc(addr), data, d3, d2, d1, d0)
            return data

        dut._log.info("WB_READ  @{} = b{} {} {} {}  NOT-RESOLVABLE", self.addr_desc(addr), d3, d2, d1, d0)
        return None


    async def wb_dump(self, addr: int, count: int) -> int:
        self.check_enable()
        addr = self.check_address(addr)
        assert count % 4 == 0, f"count = {count} not aligned to modulus 4"
        offset = 0
        left = count
        while left > 0:
            (d32, d0, d1, d2, d3) = await self.wb_read_BinaryValue(addr)
            s0 = chr(d0) if(d0.is_resolvable and chr(d0.integer).isprintable()) else '.'
            s1 = chr(d1) if(d1.is_resolvable and chr(d1.integer).isprintable()) else '.'
            s2 = chr(d2) if(d2.is_resolvable and chr(d2.integer).isprintable()) else '.'
            s3 = chr(d3) if(d3.is_resolvable and chr(d3.integer).isprintable()) else '.'
            data = "0x{:08x}".format(d32.integer) if(d32.is_resolvable) else '0x????????'
            offstr = "@+0x{:04x}".format(offset) if(addr != offset) else ''
            self._dut._log.info("WB_DUMP  @{}{} = {}  b{} {} {} {}  {}  {}{}{}{}".format(self.addr_desc(addr), offstr, data, d3, d2, d1, d0, d32, s0, s1, s2, s3))
            left -= 4
            addr += 4
            offset += 4
        return count


__all__ = [
    'WishBone'
]
