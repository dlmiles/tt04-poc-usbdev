#
#
#
#
#
#
import random
import cocotb

from usbtester.UsbBitbang import *


# This will take integer data and deliberately invalidate/corrupt at
#  least one bit using random and XOR
def invalidate(value: int, width: int) -> int:
    assert width > 0 and width <= 32, f"width invalid: {width}"
    mask = (1 << width) - 1
    for i in range(1000):
        xor = random.randint(1, mask)
        if xor != 0:	# should not be the case with randint(a=1, ...)
            return value ^ xor
    assert False, f"invalidate failed: {value} {width}"


async def test_bitbang_token(dut,
    usb: UsbBitbang,
    token: int,
    sync_count: int = 1,
    invalid_token: bool = False,
    invalid_crc5: bool = False,
    eop_count: int = 1
    ):
    # SYNC sequence 8'b00000001  KJKJKJKK
    # FIXME check we can hold a random number of J-IDLE states here
    for i in range(sync_count):
        await usb.send_0()	# LSB0
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_1()	# MSB7

    # TOKEN=SETUP  PID=0010b 1101b
    token_hi = invalidate(~token & 0xf, 4)

    # FIXME use token this is SETUP hardcoded
    await usb.send_1()  # LSB0
    await usb.send_0()
    await usb.send_1()
    await usb.send_1()
    await usb.send_0()
    if invalid_token:
        await usb.send_0()	# invalid
    else:
        await usb.send_1()	# valid
    await usb.send_0()
    await usb.send_0()  # MSB7

    # Sending ADDR=0000001b is ignored after RESET, maybe can setup REG_ADDRESS(addr=1,enable=true)
    # ADDR=0000000b
    await usb.send_0()  # LSB0
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB6

    # ENDP=0000b
    await usb.send_0()  # LSB0
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB3

    # CRC5=11101b 0x1d (a=0x01, e=0x0)
    # CRC5=00010b 0x02 (a=0x00, e=0x0)
    await usb.send_0()  # LSB0
    if invalid_crc5:
        await usb.send_0()	# invalid
    else:
        await usb.send_1()	# valid
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB4

    for i in range(eop_count):
        await usb.send_eop()	# EOP - SE0 SE0 J

    await usb.set_idle()


async def test_bitbang_packet(dut,
    usb: UsbBitbang,
    pid: int,
    payload: tuple,
    crc16: int,
    sync_count: int = 1,
    invalid_pid: bool = False,
    invalid_payload: bool = False,
    invalid_crc16: bool = False,
    eop_count: int = 1
    ):
    for i in range(sync_count):
        await usb.send_sync()    # SYNC 8'b00000001 0x80 KJKJKJKK

    if invalid_pid:
        pid = invalidate(pid, 8)
    await usb.send_pid(pid=pid, allow_invalid=True)

    for i32 in payload:
        if invalid_payload:
            i32 = invalidate(i32, 32)
        #await usb.send_data(setup[0], 32)	# DATA[0..3]
        #await usb.send_data(setup[1])		# DATA[4..7]
        await usb.send_data(i32, 32)		# DATA[4..7]

    if invalid_crc16:
        crc16 = invalidate(crc16, 16)
    await usb.send_data(crc16, 16, "CRC16")	# CRC16

    for i in range(eop_count):
        await usb.send_eop()	# EOP - SE0 SE0 J

    await usb.set_idle()


async def test_bitbang_token_stuffing(dut,
    usb: UsbBitbang,
    token: int,
    sync_count: int = 1,
    invalid_token: bool = False,
    invalid_crc5: bool = False,
    eop_count: int = 1,
    stuffing_error: int = 0
    ):

    # SYNC sequence 8'b00000001  KJKJKJKK
    # FIXME check we can hold a random number of J-IDLE states here
    for i in range(sync_count):
        await usb.send_0()	# LSB0
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_0()
        await usb.send_1()	# MSB7

    if stuffing_error == 1:	# immedately after SYNC
        await usb.send_same(count=7)

    # TOKEN=SETUP  PID=0010b 1101b
    token_hi = invalidate(~token & 0xf, 4)

    # FIXME use token this is SETUP hardcoded
    await usb.send_1()  # LSB0
    await usb.send_0()
    await usb.send_1()
    await usb.send_1()
    await usb.send_0()
    if invalid_token:
        await usb.send_0()	# invalid
    else:
        await usb.send_1()	# valid
    await usb.send_0()
    await usb.send_0()  # MSB7

    if stuffing_error == 2:	# immedately after TOKEN/PID
        await usb.send_same(count=7)

    # Sending ADDR=0000001b is ignored after RESET, maybe can setup REG_ADDRESS(addr=1,enable=true)
    # ADDR=0000000b
    await usb.send_0()  # LSB0
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB6

    if stuffing_error == 3:	# middle of data
        await usb.send_same(count=7)

    # ENDP=0000b
    await usb.send_0()  # LSB0
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB3

    if stuffing_error == 4:	# end of data
        await usb.send_same(count=7)

    # CRC5=11101b 0x1d (a=0x01, e=0x0)
    # CRC5=00010b 0x02 (a=0x00, e=0x0)
    await usb.send_0()  # LSB0
    if invalid_crc5:
        await usb.send_0()	# invalid
    else:
        await usb.send_1()	# valid
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB4

    if stuffing_error == 5:	# before EOP
        await usb.send_same(count=7)

    for i in range(eop_count):
        await usb.send_eop()	# EOP - SE0 SE0 J

    if stuffing_error == 6:	# after EOP
        await usb.send_same(count=7)

    await usb.set_idle()


async def test_bitbang_packet_stuffing(dut,
    usb: UsbBitbang,
    pid: int,
    payload: tuple,
    crc16: int,
    sync_count: int = 1,
    invalid_pid: bool = False,
    invalid_payload: bool = False,
    invalid_crc16: bool = False,
    eop_count: int = 1,
    stuffing_error: int = 0
    ):
    for i in range(sync_count):
        await usb.send_sync()    # SYNC 8'b00000001 0x80 KJKJKJKK

    if stuffing_error == 1:	# immedately after SYNC
        await usb.send_same(count=7)

    if invalid_pid:
        pid = invalidate(pid, 8)
    await usb.send_pid(pid=pid, allow_invalid=True)

    if stuffing_error == 2:	# immedately after PID
        await usb.send_same(count=7)

    for i32 in payload:
        if invalid_payload:
            i32 = invalidate(i32, 32)
        #await usb.send_data(setup[0], 32)	# DATA[0..3]
        #await usb.send_data(setup[1])		# DATA[4..7]
        await usb.send_data(i32, 32)		# DATA[4..7]
        if stuffing_error == 3:	# middle of data
            await usb.send_same(count=7)
            stuffing_error = 0	# only inject error once

    if stuffing_error == 4:	# end of data
        await usb.send_same(count=7)

    if invalid_crc16:
        crc16 = invalidate(crc16, 16)
    await usb.send_data(crc16, 16, "CRC16")	# CRC16

    if stuffing_error == 5:	# before EOP
        await usb.send_same(count=7)

    for i in range(eop_count):
        await usb.send_eop()	# EOP - SE0 SE0 J

    if stuffing_error == 6:	# after EOP
        await usb.send_same(count=7)

    await usb.set_idle()


__ALL__ = [
    'invalidate',
    'test_bitbang_token',
    'test_bitbang_packet',
    'test_bitbang_token_stuffing',
    'test_bitbang_packet_stuffing'
]
