#!/usr/bin/python3
#
#
import os
import sys
import re
import inspect

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles
from cocotb.wavedrom import trace
from cocotb.binary import BinaryValue

from usbtester import *
from usbtester.cocotbutil import *
from usbtester.TT2WB import TT2WB
from usbtester.UsbDevDriver import UsbDevDriver
import usbtester.RomReader

###
###
##################################################################################################################################
###
###

async def send_in7_oneedge(dut, in7):
    in7_before = dut.in7.value
    out8_before = dut.out8.value
    clk_before, = dut.clk.value
    in8 = try_integer(dut.in7.value, 0) << 1 | try_integer(dut.clk.value, 0)	# rebuild for log output
    dut.in7.value = in7
    if dut.clk.value:
        await FallingEdge(dut.clk)
    else:
        await RisingEdge(dut.clk)
    # Try to report non-clock state changes
    out8_equal = try_compare_equal(out8_before, dut.out8.value)
    if True or in7_before != in7 or not out8_equal:
        out8_desc = "SAME" if(out8_equal) else "CHANGED"
        dut._log.info("dut clk={} in7={} {} in8={} {}  =>  out8={} {} => {} {}  [{}]".format(
            clk_before,
            try_binary(dut.in7.value, width=7),  try_decimal_format(try_integer(dut.in7.value), '3d'),
            try_binary(in8, width=8),            try_decimal_format(try_integer(in8), '3d'),
            try_binary(out8_before, width=8),    try_decimal_format(try_integer(out8_before), '3d'),
            try_binary(dut.out8.value, width=8), try_decimal_format(try_integer(dut.out8.value), '3d'),
            out8_desc))

async def send_in7(dut, in7):
    in8 = try_integer(dut.in7.value, 0) << 1 | try_integer(dut.clk.value, 0)	# rebuild for log output
    dut._log.info("dut out8={} in7={} in8={}".format(dut.out8.value, dut.in7.value, in8))
    await FallingEdge(dut.clk)
    dut.in7.value = in7
    await RisingEdge(dut.clk)
    dut._log.info("dut out8={} in7={} in8={}".format(dut.out8.value, dut.in7.value, in8))

async def send_in8(dut, in8):
    in7 = (in8 >> 1) & 0x7f
    await send_in7(dut, in7)

async def send_in8_oneedge(dut, in8):
    want_clk = in8 & 0x01
    # The rom.txt scripts expect to drive CLK as well, so we need to align edge so current
    #  state is mismatched
    if dut.clk.value and want_clk != 0:
        if dut.clk.value:
            dut._log.warning("dut ALIGN INSERT EDGE: Falling (clk={}, want_clk={})".format(dut.clk.value, want_clk))
            await FallingEdge(dut.clk)
        else:
            dut._log.warning("dut ALIGN INSERT EDGE: Rising (clk={}, want_clk={})".format(dut.clk.value, want_clk))
            await RisingEdge(dut.clk)
    in7 = (in8 >> 1) & 0x7f
    await send_in7_oneedge(dut, in7)

async def send_sequence_in8(dut, seq):
    for in8 in seq:
        await send_in8(dut, in8)

###
###
##################################################################################################################################
###
###

# Signals we are not interesting in enumerating at the top of the log
exclude = [
    r'[\./]_',
    r'[\./]FILLER_',
    r'[\./]PHY_',
    r'[\./]TAP_',
    r'[\./]VGND',
    r'[\./]VNB',
    r'[\./]VPB',
    r'[\./]VPWR',
    r'[\./]pwrgood_'
]
EXCLUDE_RE = dict(map(lambda k: (k,re.compile(k)), exclude))

def exclude_re_path(path: str, name: str):
    for v in EXCLUDE_RE.values():
        if v.search(path):
            #print("EXCLUDED={}".format(path))
            return False
    return True

def resolve_GL_TEST():
    gl_test = False
    if 'GL_TEST' in os.environ:
        gl_test = True
    if 'GATES' in os.environ and os.environ['GATES'] == 'yes':
        gl_test = True
    return gl_test


def grep_file(filename: str, pattern1: str, pattern2: str) -> bool:
    # FIXME maybe we exec sed -e '' -i filename?
    # PRODUCTION
    # -  assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0e933f);
    # -  assign rx_timerLong_reset = (rx_timerLong_counter == 23'h07403f);
    # -  assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h021fbf);
    # SIM
    # +  assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0012a7);
    # +  assign rx_timerLong_reset = (rx_timerLong_counter == 23'h000947);
    # +  assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h0002b7);
    with open(filename) as file_in:
        lines = []
        for line in file_in:
            lines.append(line.rstrip())
        left = list(filter(lambda l: re.search(pattern1, l), lines))
        # search for a single line match of pattern1 in the whole file (error if not found, or multiple lines)
        if len(left) == 1:
            # search the line found for pattern2 and return True/False on this
            retval = re.search(pattern2, left[0])
            #print("left={} {}".format(left[0], retval))
            return retval
    raise Exception(f"Unable to find any match from file: {filename} for regex {pattern1}")



## FIXME see if we can register multiple items here (to speed up simulation?) :
##   signal, prefix/label, lambda on change, lambda on print
##  want to have some state changes lookup another signal to print
@cocotb.coroutine
def monitor(dut, path: str, prefix: str = None) -> None:
    value = None

    def printable(v) -> str:
        if v.is_resolvable and path.endswith('_string'):
            # Convert to string
            return v.buff.decode('ascii').rstrip()
        else:
            return str(v.value)

    signal = design_element(dut, path)
    if signal is None:
        raise Exception(f"Unable to find signal path: {path}")
        
    pfx = prefix if(prefix) else path

    value = signal.value
    dut._log.info("monitor({}) = {} [STARTED]".format(pfx, printable(value)))

    while True:
        # in generator-based coroutines triggers are yielded
        yield ClockCycles(dut.clk, 1)
        new_value = signal.value
        if new_value != value:
            s = printable(new_value)
            dut._log.info("monitor({}) = {}".format(pfx, s))
            value = new_value



## FIXME fix the cocotb timebase for 100MHz and 48MHz (or 192MHz and 48MHz initially)
## FIXME add assert to confirm elapsed realtime

EP_COUNT = 4
ADDRESS_LENGTH = 84
MAX_PACKET_LENGTH = 40

@cocotb.test()
async def test_usbdev(dut):
    if 'DEBUG' in os.environ and os.environ['DEBUG'] != 'false':
        dut._log.setLevel(cocotb.logging.DEBUG)
    dut._log.info("start")
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())

    dumpvars = ['CI', 'GL_TEST', 'FUNCTIONAL', 'USE_POWER_PINS', 'SIM', 'UNIT_DELAY', 'SIM_BUILD', 'GATES', 'ICARUS_BIN_DIR', 'COCOTB_RESULTS_FILE', 'TESTCASE', 'TOPLEVEL']
    if 'CI' in os.environ and os.environ['CI'] != 'false':
        for k in os.environ.keys():
            if k in dumpvars:
                dut._log.info("{}={}".format(k, os.environ[k]))

    depth = None
    GL_TEST = resolve_GL_TEST()
    if GL_TEST:
        dut._log.info("GL_TEST={} (detected)".format(GL_TEST))
        #depth = 1

    report_resolvable(dut, 'initial ', depth=depth, filter=exclude_re_path)

    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    dut.ena.value = 0

    # This is a simulator async kludge, I need to break the X state (I don't care if with 0 or 1)
    # If it started up as a 1, we just clock a few more times (like 3 edges) to clear it.
    ele = design_element(dut, 'dut')
    print("A ele={} {}".format(try_path(ele), try_value(ele)))
    if ele:
        ele1 = design_element(ele, 'async_reset_ctrl')
        print("A ele1={} {}".format(try_path(ele1), try_value(ele1)))
        if ele1:
            ele2 = design_element(ele1, 'sim_reset')
            print("A ele2={} {}".format(try_path(ele2), try_value(ele2)))

    ele = design_element(dut, 'dut')
    print("B ele={} {}".format(try_path(ele), try_value(ele)))
    if ele:
        ele1 = design_element(ele, 'sim_reset')
        print("B ele1={} {}".format(try_path(ele1), try_value(ele1)))

    ele = design_element(dut, 'dut')
    print("C ele={} {}".format(try_path(ele), try_value(ele)))
    if ele:
        ele1 = design_element(ele, 'sync_reset')
        print("C ele1={} {}".format(try_path(ele1), try_value(ele1)))

    ele = design_element(dut, 'dut.sim_reset')
    print("D ele={} {}".format(try_path(ele), try_value(ele)))
    ele = design_element(dut, 'dut.async_reset_ctrl')
    print("E ele={} {}".format(try_path(ele), try_value(ele)))
    ele = design_element(dut, 'dut.async_reset_ctrl.sim_reset')
    print("F ele={} {}".format(try_path(ele), try_value(ele)))

    await ClockCycles(dut.clk, 6)

    print("design_element_exists({})={}".format('dut.sim_reset',  design_element_exists(dut, 'dut.sim_reset')))
    print("design_element_exists({})={}".format('dut.sync_reset', design_element_exists(dut, 'dut.sync_reset')))

    # signal not present during GL_TEST
    if design_element_exists(dut, 'dut.sim_reset'):
        dut.sim_reset.value = 0
        await ClockCycles(dut.clk, 1)
        dut.sim_reset.value = 1
        await ClockCycles(dut.clk, 1)
        dut.sim_reset.value = 0
        await ClockCycles(dut.clk, 1)
    elif design_element_exists(dut, 'dut.sync_reset') and not GL_TEST:
        # GL_TEST forcing a sync reset
        # We would not need to do this if we can instruct icarus to initialize the
        #   sr_latch to any state on powerup (not X state).
        dut.sync_reset.value = 0
        await ClockCycles(dut.clk, 1)
        dut.sync_reset.value = 1
        await ClockCycles(dut.clk, 1)
        dut.sync_reset.value = 0
        await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 6)
    

    dut.ena.value = 1
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 4)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)

    ele = design_element(dut, 'dut.sim_reset')
    print("GG ele={} {}".format(try_path(ele), try_value(ele)))
    ele = design_element(dut, 'dut.sync_reset')
    print("HH ele={} {}".format(try_path(ele), try_value(ele)))


    ## FIXME move this stuff to testing tt04_to_wishbone.v separately
    dut.uio_in.value = 0x20
    dut.ui_in.value = 0x01
    await ClockCycles(dut.clk, 1)
    #while dut.dut.wb_ACK.value == 0:
    #    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x00
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x05	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)


    dut.uio_in.value = 0x40
    dut.ui_in.value = 0x21	# AD0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x60
    dut.ui_in.value = 0x43	# AD1
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x80
    dut.ui_in.value = 0x98	# DO0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x80
    dut.ui_in.value = 0xba	# DO1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x80
    dut.ui_in.value = 0xdc	# DO2
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0x80
    dut.ui_in.value = 0xfe	# DO3
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x07	# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, 4):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x05	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x07	# EXE_WRITE
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, 4):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x05	# EXE_ENABLE
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x06	# EXE_READ
    await ClockCycles(dut.clk, 1)

    while not extract_bit(dut.dut.uio_out.value, 4):
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x04	# EXE_DISABLE
    await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0x20	# EXEC
    dut.ui_in.value = 0x01	# EXE_RESET
    await ClockCycles(dut.clk, 1)

    await ClockCycles(dut.clk, 256)

    # Start these now as they will fire during USB interface RESET sequence
    # Defered the other FSM monitors setup due to significant simulation slowdown
    await cocotb.start(monitor(dut, 'dut.usbdev.interrupts',                               'interrupts'))
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string',     'main'))

    debug(dut, '001_WISHBONE')

    ttwb = TT2WB(dut)


    await ttwb.exe_reset()

    await ttwb.exe_enable()

    await ttwb.idle()

    await ttwb.exe_disable()

    await ttwb.idle()

    await ttwb.exe_enable()

    await ttwb.exe_write(0x1234, 0xfedcba98)
    # test write cycle over WB
    await ttwb.exe_write(0xff80, 0xff80fe7f)
    # test write cycle over WB

    v = await ttwb.exe_read(0x0000)
    # v == xxxxxxxx (uninit mem inside usbdev)

    await ttwb.idle()

    await ttwb.exe_write(0x0000, 0x76543210)

    v = await ttwb.exe_read(0x0000)
    assert(v == 0x76543210), f"unexpected readback of WB_READ(0x0000) = 0x{v:x} (expected 0x76543210)"

    await ttwb.exe_write(0x0000, 0x00000000)

    v = await ttwb.exe_read(0x0000)
    assert(v == 0x00000000), f"unexpected readback of WB_READ(0x0000) = 0x{v:x} (expected 0x00000000)"

    await ttwb.exe_disable()

    await ttwb.exe_reset()


    await ttwb.exe_enable()

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)

    for a in range(0, ADDRESS_LENGTH+1, 4):
        i = a & 0xff
        d = ((i+3) << 24) | ((i+2) << 16) | ((i+1) << 8) | (i)
        await ttwb.exe_write(a, d)

    end_of_buffer = -1
    for a in range(0, ADDRESS_LENGTH+1, 4):
        i = a & 0xff
        expect = ((i+3) << 24) | ((i+2) << 16) | ((i+1) << 8) | (i)
        d = await ttwb.exe_read_BinaryValue(a)
        if d[0].is_resolvable:
            assert d[0] == expect, f"read at {a} expected {expect} got {d[0]}"
        elif end_of_buffer == -1:
            end_of_buffer = a	# stop at first non resolvable
    dut._log.info("END_OF_BUFFER = 0x{:04x} {}d".format(end_of_buffer, end_of_buffer))


    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)

    await ttwb.wb_dump(REG_FRAME, 0x30)


    for a in range(0, ADDRESS_LENGTH+1, 4):	# zero out memory buffer
        await ttwb.exe_write(a, 0x00000000)

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)

    await ClockCycles(dut.clk, 256)

    # Confirmed repeated memory buffer from 0x0000 to 0x7fff
    # From 0x8000 zeros until 0xff00
    # Then readable registers visible of zeros
    #await ttwb.wb_dump(0x0000, 0x10000)

    report_resolvable(dut, depth=depth, filter=exclude_re_path)

    await ClockCycles(dut.clk, 256)

    driver = UsbDevDriver(dut, ttwb)

    await driver.setup()

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)

    # Perform reset sequence
    #reset_seq = [0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    #await send_sequence_in8(dut, reset_seq)

    await ClockCycles(dut.clk, 256)

    PHY_CLK_FACTOR = 8	# 4 per edge
    OVERSAMPLE = 4	# 48MHz / 12MHz
    TICKS_PER_BIT = PHY_CLK_FACTOR * OVERSAMPLE

    # FIXME why are both the WriteEnable high for output at startup

    # TODO work out how to get the receiver started
    #  for a start writeEnable of DP&DM is set
    dut.uio_in.value = dut.uio_in.value | 0x08	# POWER bit3
    await ClockCycles(dut.clk, 128)

    usb = NRZI(dut, TICKS_PER_BIT = TICKS_PER_BIT)

    debug(dut, '002_RESET')

    #############################################################################################
    # Reset 10ms (ok this sequnce works but takes too long to simulate, for test/debug)
    await usb.send_SE0()	# !D+ bit0 !D- bit1 = SE0 RESET

    # FIXME
    reset_ticks = int((48000000 / 100) * PHY_CLK_FACTOR)	# 48MHz for 10ms

    ## auto-detect and also

    ##egrep "rx_timerLong_reset =" UsbDeviceTop.v # 23'h07403f ## FULL
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h07403f"):
        ticks = reset_ticks	## ENABLE

    ## egrep "rx_timerLong_reset =" UsbDeviceTop.v ## 23'h000947
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h000947"):
        ticks = int(reset_ticks / 200)	## ENABLE 1/200th
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SIM-MODE-200th = {}".format(reset_ticks, ticks))
        if 'CI' in os.environ and os.environ['CI'] == 'true':
            dut._log.warning("You are building GDS for production but are using UsbDeviceTop.v with simulation modified timer values".format(reset_ticks, ticks))
            exit(1)	## failure ?

    #ticks = 0		## DISABLE

    if ticks > 38400:
        PER_ITER = 38400
        dut._log.info("RESET ticks = {} ({}-per-iteration)".format(ticks, PER_ITER))
        for i in range(0, int(ticks / PER_ITER)):
            await ClockCycles(dut.clk, PER_ITER)
            total_ticks = (i+1)*PER_ITER
            dut._log.info("RESET ticks = {} of {} {:3d}%".format(total_ticks, ticks, int((total_ticks / ticks) * 100.0)))
    elif ticks > 0:
        await ClockCycles(dut.clk, ticks)
    else:
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SKIPPED".format(reset_ticks))

    v = await ttwb.wb_read(REG_INTERRUPT, format_reg_interrupt)
    assert v & 0x00010000 != 0, f"REG_INTERRUPT expected to see: RESET"
    # FIXME check out the RC status is correct or if it should be RWC
    await ttwb.wb_write(REG_INTERRUPT, 0x00010000, format_reg_interrupt)
    v = await ttwb.wb_read(REG_INTERRUPT, format_reg_interrupt)	# RC
    if v & 0x00010000 != 0:
        dut._log.warning("REG_INTERRUPT expected to see: RESET bit clear {:08x}".format(v))
    #assert v & 0x00010000 == 0, f"REG_INTERRUPT expected to see: RESET bit clear"
    #assert v == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{v:08x}"

    # FIXME
    # REG_INTERRUPT also has 0x0010000 set for DISCONNECT
    await ttwb.wb_write(REG_INTERRUPT, 0x00100000, format_reg_interrupt)
    v = await ttwb.wb_read(REG_INTERRUPT)	# RC
    if v & 0x00100000 != 0:
        dut._log.warning("REG_INTERRUPT expected to see: DISCONNECT bit clear {:08x}".format(v))

    # FIXME fetch out before and check ATTACHED
    # FIXME fetch out before and check POWERED
    # FIXME fetch out 'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string' == 'ACTIVE_INIT'  011b

    ## LS mode is setup by IDLE state D- assertion
    ## HS mode (default) is setup by IDLE state D+ assertion
    ## FS mode needs a K-chirp for 1ms just after host RESET, then readback of K-J within 100us lasting 50us
    #     need to understand the 3-K-J chirp rule, if that is the chirp sequence repeats without timeframes

    await ClockCycles(dut.clk, TICKS_PER_BIT)

    ##############################################################################################

    # These were defered so speed up the RESET simulation part
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.phy_logic.rx_packet_stateReg_string', 'rx_packet'))
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.phy_logic.tx_frame_stateReg_string',  'tx_frame'))
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.active_stateReg_string',   'active'))
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.token_stateReg_string',    'token'))
    
    ##############################################################################################

    debug(dut, '003_SETUP_BITBANG')

    await usb.send_idle()

    # SYNC sequence 8'b00000001  KJKJKJKK
    # FIXME check we can hold a random number of J-IDLE states here
    await usb.send_0()	# LSB0
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()
    await usb.send_1()	# MSB7

    # TOKEN=SETUP  PID=0010b 1101b
    await usb.send_1()  # LSB0
    await usb.send_0()
    await usb.send_1()
    await usb.send_1()
    await usb.send_0()
    await usb.send_1()
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
    await usb.send_1()
    await usb.send_0()
    await usb.send_0()
    await usb.send_0()  # MSB4

    await usb.send_eop()	# EOP - SE0 SE0 J


    await usb.send_sync()    # SYNC 8'b00000001 0x80 KJKJKJKK

    # DATA0 PID=8'b1100_0011 0xc3
    await usb.send_data(0xc3, 8)

    setup = (0x04030201, 0x08070605, 0x304f)
    #setup = (0x00000000, 0x00000000, 0xf4bf)
    #setup = (0xffffffff, 0xffffffff, 0x70fe)
    await usb.send_data(setup[0], 32)	# DATA[0..3]
    await usb.send_data(setup[1])	# DATA[4..7]
    await usb.send_data(setup[-1], 16)	# CRC16

    await usb.send_eop()	# EOP - SE0 SE0 J

    await usb.send_idle()

    #await ClockCycles(dut.clk, TICKS_PER_BIT*256)

    v = await ttwb.wb_read(REG_INTERRUPT)
    assert v & INTR_EP0SETUP != 0, f"REG_INTERRUPT expected to see: EP0SETUP"
    await ttwb.wb_write(REG_INTERRUPT, INTR_EP0SETUP)	# UVM=W1C
    v = await ttwb.wb_read(REG_INTERRUPT)
    if v & INTR_EP0SETUP != 0:
        dut._log.warning("REG_INTERRUPT expected to see: EP0SETUP bit clear {:08x}".format(v))
    assert v & INTR_EP0SETUP == 0, f"REG_INTERRUPT expected to see: EP0SETUP bit clear"
    assert v == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{v:08x}"

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)

    # Validate 8 bytes of SETUP made it into the buffer location
    v = await ttwb.wb_read(REG_SETUP0)
    assert v == setup[0], f"SETUP0 expected to see: SETUP payload+0 0x{setup[0]:08x} is 0x{v:08x}"
    v = await ttwb.wb_read(REG_SETUP1)
    assert v == setup[1], f"SETUP1 expected to see: SETUP payload+4 0x{setup[1]:08x} is 0x{v:08x}"


    # FIXME check state machine for error (move these tests noise/corruption tests to another suite)
    # Checking state machine ERROR indication and recovery

    # Inject noise into the signals, clock/1

    # Inject noise into the signals, clock/2

    # Inject noise into the signals, clock/4 (these start to look like real random data bits)

    # Inject valid packet after noise (at various lengths), check for success,
    #  if not retry valid packet, expect 1st packet maybe to work, but 2nd packet to always work, confirming retransmission, clock/4
    
    # Inject valid looking SYNC sequence then noise at various lengths
    # Send packet, maybe it worked, if not retransmit, confirm by now it always worked


    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)

    await ClockCycles(dut.clk, 512)
    # FIXME write helper to check TX busy and wait idle (dont but now manage ability test observed states seen, and states never seen, to provide test true/false result)
    # Wait for TX of SYNC+ACK  (0x80 + 0xd2)
    
    # FIXME here the hardware auto ACKed the SETUP (see above, but validate data in certain states for example PID=ACK)

    # FIXME perform SETUP SET_ADDRESS to non-zero and switch for the remainer of the tests below
    # FIXME this better tests realworld expectations
    
    # FIXME test addr/endp filter rejection (after the addr setup and switch check filter)

    ADDRESS = 0x000
    ENDPOINT = 0x0

    ####
    #### 004 SETUP no data
    ####

    debug(dut, '004_SETUP_TOKEN')

    # mimic a 12byte IN payload delivered over 2 packets
    # setup device to respond to IN for addr=0x000 endp=0x0 with 8 bytes of payload

    await driver.halt(endp=ENDPOINT) # HALT EP=0
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=8))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_OUT, interrupt=True))
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0), max_packet_size=20))
    await driver.unhalt(endp=ENDPOINT)

    await usb.send_token(usb.SETUP, addr=ADDRESS, endp=ENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
    debug(dut, '004_SETUP_DATA0')
    setup = (0x04030201, 0x08070605) # crc16=0x304f
    await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
    await usb.send_idle()

    await ClockCycles(dut.clk, 17)	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+1=17
    ## Manage interrupt and reset
    ## FIXME write helper to access dut.dut.interrupts (from extenal interface)
    assert dut.dut.interrupts.value != 0, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
    assert data & INTR_EP0SETUP != 0, f"REG_INTERRUPT expects EP0SETUP to fire {v:08x}"
    await ttwb.wb_write(REG_INTERRUPT, INTR_EP0SETUP, regdesc)
    data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
    assert data & INTR_EP0SETUP == 0, f"REG_INTERRUPT expects EP0SETUP to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert dut.dut.interrupts.value == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"

    # Validate 8 bytes of SETUP made it into the buffer location
    data = await ttwb.wb_read(REG_SETUP0, regdesc)
    assert data == setup[0], f"SETUP0 expected to see: SETUP payload+0 0x{setup[0]:08x} is 0x{v:08x}"
    data = await ttwb.wb_read(REG_SETUP1, regdesc)
    assert data == setup[1], f"SETUP1 expected to see: SETUP payload+4 0x{setup[1]:08x} is 0x{v:08x}"

    debug(dut, '004_SETUP_ACK')

    # FIXME check tx_state cycles and emits ACK
    await ClockCycles(dut.clk, TICKS_PER_BIT*24)	# let TX run auto ACK

    debug(dut, '004_SETUP_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*16)	# gap to next test
    
    ####
    #### 005  EP0 with IN (enumeration device-to-host response)
    ####

    debug(dut, '005_EP0_IN')

    # Setup driver with data in buffer and expect the driver to manage sending
    # For example as a response to SETUP
    await driver.halt(endp=ENDPOINT)
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=8))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_IN, interrupt=True))
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0), max_packet_size=8))
    await ttwb.wb_write(BUF_DATA0, 0x14131211)
    await ttwb.wb_write(BUF_DATA1, 0x18171615)
    await driver.unhalt(endp=ENDPOINT)

    await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)	# host sents IN calling for data
    await usb.send_idle()

    debug(dut, '005_EP0_IN_TX_DATA0')
    
    # FIXME assert we saw request
    

    await ClockCycles(dut.clk, TICKS_PER_BIT*8*13)	## wait for TX to finish
    await ClockCycles(dut.clk, TICKS_PER_BIT*3)

    # FIXME inject delay here to confirm timer limits against spec

    debug(dut, '005_EP0_IN_RX_ACK')
    await usb.send_handshake(usb.ACK)	# host ACKing
    await usb.send_idle()

    await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for TX to finish

    ## FIXME check out why there is no interrupt raised for EP0 completion (maybe because we are not expected to operate here but on another address after SET_ADDRESS)
    #assert dut.dut.interrupts.value != 0, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    #assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {v:08x}"
    #await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regdesc)
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert dut.dut.interrupts.value == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"

    ## FIXME this doesn't seem correct to me
    data = await ttwb.wb_read(REG_EP0, regrd)
    # This is not useful
    assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
    data = await ttwb.wb_read(BUF_DESC0, lambda v,a: desc0_format(v))
    assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
    ## FIXME this is surely wrong!  code=INPROGRESS
    assert data & 0x000f0000 == 0x000f0000, f"DESC0 expected code={data:08x}"
    data = await ttwb.wb_read(BUF_DESC1, lambda v,a: desc1_format(v))
    data = await ttwb.wb_read(BUF_DESC2, lambda v,a: desc2_format(v))
    ## FIXME IMHO if this was successful, there is insufficient indication of that succcess

    debug(dut, '005_EP0_IN_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### 006  EP0 with OUT (enumeration host-to-device command)
    ####

    debug(dut, '006_EP0_OUT')

    # Setup driver with data in buffer and expect the driver to manage receiving
    # For example as a response to SETUP
    await driver.halt(endp=ENDPOINT)
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=8))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_OUT, interrupt=True))
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0), max_packet_size=8))
    #await ttwb.wb_write(BUF_DATA0, 0x94939291)
    #await ttwb.wb_write(BUF_DATA1, 0x97969594)
    await driver.unhalt(endp=ENDPOINT)

    await usb.send_token(usb.OUT, addr=ADDRESS, endp=ENDPOINT)	# host sents IN calling for data

    debug(dut, '006_EP0_OUT_RX_DATA0')

    payload = (0xfbfaf9f8, 0xfffefdfc)
    await usb.send_crc16_payload(usb.DATA0, Payload.int32(*payload))	# host sends OUT calling for data
    await usb.send_idle()

    await ClockCycles(dut.clk, 17)	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+1=17
    ## FIXME check out why there is no interrupt raised for EP0 completion (maybe because we are not expected to operate here but on another address after SET_ADDRESS)
    #assert dut.dut.interrupts.value != 0, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    #assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {v:08x}"
    #await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regdesc)
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert dut.dut.interrupts.value == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"

    ## FIXME this doesn't seem correct to me
    data = await ttwb.wb_read(REG_EP0, regrd)
    # This is not useful
    assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
    data = await ttwb.wb_read(BUF_DESC0, lambda v,a: desc0_format(v))
    assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
    ## FIXME this is surely wrong!  code=INPROGRESS
    assert data & 0x000f0000 == 0x000f0000, f"DESC0 expected code={data:08x}"
    data = await ttwb.wb_read(BUF_DESC1, lambda v,a: desc1_format(v))
    data = await ttwb.wb_read(BUF_DESC2, lambda v,a: desc2_format(v))
    ## FIXME IMHO if this was successful, there is insufficient indication of that succcess

    # Validate 8 bytes of PAYLOAD made it into the buffer location
    data = await ttwb.wb_read(BUF_DATA0)
    assert data == payload[0], f"PAYLOAD0 expected to see: payload+0 0x{payload[0]:08x} is 0x{v:08x}"
    data = await ttwb.wb_read(BUF_DATA1)
    assert data == payload[1], f"PAYLOAD1 expected to see: payload+4 0x{payload[1]:08x} is 0x{v:08x}"

    debug(dut, '006_EP0_OUT_TX_ACK')

    ## FIXME validate the PID=ACK auto-tx here
    await ClockCycles(dut.clk, TICKS_PER_BIT*24)	## let TX run auto ACK

    debug(dut, '006_EP0_OUT_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*16)

    ####
    ####
    ####

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)

    # FIXME coroutine observing tx sending states, monitor/report in log
    
    # FIXME check hardware generated interrupt/completion

    ## observe ACK


    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### 010 
    ####
    
    ## interrupt NACK
    debug(dut, '010_IN_NAK')

    await driver.halt(endp=ENDPOINT) # HALT EP=0
    # FIXME randomize values here, set zero, 0xfffff, random to confirm DESC[012] contents do not matter (run the test 3 times)
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=0))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_IN, interrupt=False))
    # the key things for auto NACK generation are enable=True and head=0 (no descriptor, so no data)
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(0), max_packet_size=0))
    await driver.unhalt(endp=ENDPOINT)

    # USB interrupt (host driven endpoint polling)
    await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
    await usb.send_idle()

    debug(dut, '010_IN_NACK_TX_NACK')
    ## FIXME observe automatic NACK from hardware (as no descriptor is setup) but endpoint enabled
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)
    await ClockCycles(dut.clk, TICKS_PER_BIT*12)

    debug(dut, '010_IN_NACK_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)

    ####
    #### 011
    ####

    ## interrupt ACK
    debug(dut, '011_IN_ACK')

    await driver.halt(endp=ENDPOINT) # HALT EP=0
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=4))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_IN, interrupt=True))
    # This time we are enable=True and head!=0 (so the DESC[012] above is important
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0), max_packet_size=4))
    await ttwb.wb_write(BUF_DATA0, 0x0b0a0908)
    await driver.unhalt(endp=ENDPOINT)

    await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
    await usb.send_idle()


    debug(dut, '011_IN_ACK_TX_ACK')
    ## FIXME observe automatic ACK with data
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)
    await ClockCycles(dut.clk, TICKS_PER_BIT*12)

    debug(dut, '011_IN_ACK_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)

    ## FIXME confirm the hardwre is capable of auto-arming the same data
    ##   without the need for CPU interrupts, without the need for CPU to update
    ##   any EP or DESC, so that the CPU only needs to update the data area
    ##   (potentially between HALT/UNHALT) as necessary



    ## FIXME check why after send_idle() (or really send_eop()) the line state does not look like HS idle (DP high, DM low)
    ##   this is a matter of the cocotb testing code not the DUT


    ## FIXME check the tristate of the process really do mute the input when WE.
    ##   as the RX is always running it would be problematic to see our own TX data back on the RX


    ## FIXME observe DATA0/DATA1 generation (not here, move that test)




    ####
    #### SOF token with frame 0
    ####

    debug(dut, '100_SOF_0000')

    frame = 0
    data = await ttwb.wb_read(REG_FRAME, regrd)	# 11'bxxxxxxxxxxx
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"

    debug(dut, '100_SOF_0000_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### SOF token with frame 1
    ####

    debug(dut, '101_SOF_0001')

    frame = 1
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"

    debug(dut, '101_SOF_0001_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### SOF token with frame 2047
    ####

    debug(dut, '103_SOF_2047')

    frame = 2047
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"

    debug(dut, '103_SOF_2047_END')
    #await ClockCycles(dut.clk, TICKS_PER_BIT*32)
    # minimal delay, confirm back-to-back decoding works

    ####
    #### SOF token with frame 42
    ####

    debug(dut, '104_SOF_0042')

    frame = 42
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"

    debug(dut, '104_SOF_0042_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ## FIXME target other addresses confirm we ignore
    ## FIXME target other endpoints confirm we ignore (enable say endp=3 confirm we NACK) disable confirm we ignore
    ## FIXME target other endpoint=15 (which we don't support always ignores) 
        
    debug(dut, '999_DONE')

    ## This is what a real CDC dialog might look like after SETUP-default, SET_ADDRESS, SETUP-emeration
    ## FIXME write a CDC enumeration sequence
    ## FIXME write a CDC data transfer sequence

    ## GET_LINE_ENCODING=0x21
    ## EP0 Class Request IN  (0x21) 00 C2 01 00 00 00 08 (8N1 @115200 0x1c200 little-endian)
    ## EP0 Class Request IN  (0x21) 00 C2 01 00 00 00 08

    ## SET_LINE_ENCODING=0x20
    ## EP0 Class Request OUT (0x20) 00 E1 00 00 00 00 08 (8N1 @57600 0xe100)
    ## GET_LINE_ENCODING=0x21
    ## EP0 Class Request IN  (0x21) 00 E1 00 00 00 00 08

    ## SET_CONTROL_LINE_STATE=0x22
    ## EP0 Class Request OUT (0x22) no payload (no-carrier, DTE-not-present)

    ## SET_LINE_ENCODING=0x20
    ## EP0 Class Request OUT (0x20) 00 E1 00 00 00 00 08
    ## GET_LINE_ENCODING=0x21
    ## EP0 Class Request IN  (0x21) 00 E1 00 00 00 00 08

    ## SET_CONTROL_LINE_STATE=0x22
    ## EP0 Class Request OUT (0x22) no payload

    # Generate Transmited
    ## EP1 IN tsn, A1 20 00 00 00 00 02 00 00 00 (A1=bmRequestType 20=SERIAL_STATE, wValue=0x00000000, 0x0002 length, 0x0000 = bitmap)
    ##  expect ACK       ?? ?? ?? ?? <- wValue ?
    ## EP1 IN tsn, A1 20 00 00 00 00 02 00 00 00
    ##  expect ACK
    
    ## EP3 OUT tsn, 61  (host to device 1 byte)
    ##  send ACK

    ## EP2 IN tsn, 62  (device to host 1 byte)
    ##  expect ACK

    ## FIXME I assume EP2 needs to NACK when there is a poll with no new data
    ## FIXME I need to lookup if EP1 interrupts on new data (also understand USB interrupt channel semantics)

    ## FIXME write a TX/RX/WriteEnable electrical channel capture (want to add bookmarks/label/anchros,
    ##    want to mark/capture a time window, want auto-trigger on next state transition, automatic chopping of data segment,
    ##    want to output in text form, allows for easy, for USB maybe that is 01+- with WriteEnable commented)

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)


    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)

    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)
    await ClockCycles(dut.clk, 256)

    # open rom.txt and run it
    #filename = "../rom.txt"
    #limit = 1024	# sys.maxsize
    #if 'CI' in os.environ:
    #    limit = sys.maxsize	# CI no limit
    #reader = RomReader(filename)
    #count = 0
    #while count < limit and reader.has_more():
    #    await send_in8_oneedge(dut, reader.next())
    #    count += 1
    #dut._log.info("{} count={}".format(filename, count))

    report_resolvable(dut, filter=exclude_re_path)

    #halfperiod = 1	# ps
    #halfperiod = 500000	# 1_000_000ps 1_000ns 1us 1MHz
    #halfperiod = 50000	# 1_000_000ps 1_000ns 1us 10MHz
    #halfperiod = 5000000 # 0.1MHz
    #frequency = 1 / cocotb.utils.get_time_from_sim_steps(halfperiod * 2, units="us")
    #dut._log.info("{} {} {}".format(halfperiod, frequency, frequency / 1_000_000))
    #s = "" + "(%3.1fMHz)" % frequency
    #dut._log.info("s={}".format(s))
    ##frequency_a = 1 / frequency
    ##s = "" + "(%3.1fMHz)" % frequency_a
    ##dut._log.info("s={}".format(s))




# Need to make a class just to make things easier with managing payloads
# Only handles byte granularity
class Payload():
    data = bytearray()
    
    def __init__(self, data):
        # FIXME perform data conversions
        assert type(data) is bytearray, f"data is type {type(data)} and not {type(bytearray())}"
        self.data = data

    def __len__(self):
        print("Payload.len() = {}".format(len(self.data)))
        return len(self.data)

    class iterator():
        data = None
        index = 0

        def __init__(self, data):
            assert type(data) is bytearray, f"data is type {type(data)} and not {type(bytearray())}"
            self.data = bytearray(data)
            self.index = 0

        def __next__(self):
            if self.index < len(self.data):
                v = self.data[self.index]
                print("Payload.next() = {}/{} value={:02x}".format(self.index, len(self.data), v))
                self.index += 1
                return v
            print("Payload.next() = {}/{} STOP".format(self.index, len(self.data)))
            raise StopIteration()

    def __iter__(self):
        print("Payload.iter() = {}".format(len(self.data)))
        return Payload.iterator(self.data)
    

    def append(self, other: 'Payload') -> int:
        assert type(other) is Payload, f"type(other) is {type(other)} and not {type(Payload)}"
        self.data.extend(other.data)
        return self.__len__()

    @staticmethod
    def int32(*values) -> 'Payload':
        # convert to bytes
        bytes = bytearray()
        for v in values:
            bytes.append((v      ) & 0xff)
            bytes.append((v >>  8) & 0xff)
            bytes.append((v >> 16) & 0xff)
            bytes.append((v >> 24) & 0xff)
        print("int32() = {}".format(bytes))
        return Payload(bytes)




# NRZI - 0 = transition
# NRZI - 1 = no transition
# NRZI - stuff 0 after 6 111111s
class NRZI():
    # This class managed bit stream level matters concerning USB
    # It manages low-speed/high-speed difference, NRZI encoding, bit stuffing
    dut = None
    TICKS_PER_BIT = None
    LOW_SPEED = None
    nrzi_one_count = None
    nrzi_last = None

    DP = 0x01
    DM = 0x02
    MASK = DP|DM

    SE0 = 0x00		# !D+ bit0 !D- bit1 = SE0
    LS_J = DM		# !D+ bit0  D- bit1 = J   LS  IDLE
    HS_J = DP		#  D+ bit0 !D- bit1 = J   HS  IDLE
    LS_K = DP		#  D+ bit0 !D- bit1 = K   LS
    HS_K = DM		# !D+ bit0  D- bit1 = K   HS

    def __init__(self, dut, TICKS_PER_BIT: int, LOW_SPEED: bool = False):
        self.dut = dut
        assert(TICKS_PER_BIT >= 0 and type(TICKS_PER_BIT) is int)
        self.TICKS_PER_BIT = TICKS_PER_BIT
        self.LOW_SPEED = LOW_SPEED
        self.reset()
        return None

    def reset(self, last: str = None) -> None:
        self.nrzi_one_count = 0
        self.nrzi_last = last

    async def nrzi(self, whoami: str):
        assert(whoami == 'J' or whoami == 'K')
        if(self.nrzi_last != whoami):
            self.nrzi_one_count = 0
        else:
            self.nrzi_one_count += 1
        #elif not self.LOW_SPEED and whoami == 'J':
        #    self.nrzi_one_count += 1 # only stuff 1's
        #elif self.LOW_SPEED and whoami == 'K':
        #    self.nrzi_one_count += 1 # only stuff 1's
        self.nrzi_last = whoami
        if self.nrzi_one_count >= 6:
            if whoami == 'J':
                await self.send_K()
            else:
                await self.send_J()

    async def update(self, or_mask: int, ticks: int = None) -> int:
        v = self.dut.uio_in.value & ~self.MASK | or_mask
        self.dut.uio_in.value = v

        if ticks is None:
            ticks = self.TICKS_PER_BIT
        await ClockCycles(self.dut.clk, ticks)

        return v

    async def send_SE0(self) -> int:
        return await self.update(self.SE0)

    async def send_J(self) -> None:
        if self.LOW_SPEED:
            await self.update(self.LS_J)
        else:
            await self.update(self.HS_J)
        await self.nrzi('J')

    async def send_K(self) -> None:
        if self.LOW_SPEED:
            await self.update(self.LS_K)
        else:
            await self.update(self.HS_K)
        await self.nrzi('K')

    async def send_0(self) -> None:
        if self.nrzi_last == 'K':
            await self.send_J()
        elif self.nrzi_last == 'J':
            await self.send_K()
        else:
            assert False, f"use send_idle() first"

    async def send_1(self) -> None:
        if self.nrzi_last == 'K':
            await self.send_K()
        elif self.nrzi_last == 'J':
            await self.send_J()
        else:
            assert False, f"use send_idle() first"

    async def send_bf(self, bit: bool) -> None:
        if bit:
            await self.send_1()
        else:
            await self.send_0()

    async def send_idle(self) -> None:
        if self.LOW_SPEED:
            await self.update(self.LS_J)	# aka IDLE
        else:
            await self.update(self.HS_J)	# aka IDLE
        self.reset('J')

    async def send_data(self, data: int, bits: int = 32) -> None:
        assert(bits >= 0 and bits <= 32)
        print("send_data(data=0x{:08x} {:11d}, bits={})".format(data, data, bits))
        for i in range(0, bits):	# LSB first
            bv = data & (1 << i)
            bf = bv != 0
            await self.send_bf(bf)
            self.crc5_add(bf)
            self.crc16_add(bf)

    OUT = 0x1
    IN = 0x9
    SOF = 0x5
    SETUP = 0xd
    DATA0 = 0x3
    DATA1 = 0xc
    ACK = 0x2
    NACK = 0xa
    STALL = 0xe
    
    crc5 = 0
    crc16 = 0
    
    addr = 0
    endp = 0
    data0 = True

    # FIXME move these out of this class, into data layer API class
    # This class manages low level packet structure
    # SYNC+EOF and CRC5/CRC16 generation
    async def send_sync(self) -> None:
        await self.send_data(0x80, 8)

    async def send_eop(self) -> None:
        await self.send_SE0()
        await self.send_SE0()
        await self.send_J()
    

    def crc5_reset(self) -> None:
        self.crc5 = 0x1f

    def crc5_add(self, bit: bool) -> None:
        crc5 = self.crc5
        # 1bit input, right shifting
        lsb = (crc5 & 1) != 0
        crc5 = crc5 >> 1
        if bit != lsb:
            crc5 ^= 0x14	# b10100
        self.crc5 = crc5

    def crc5_valid(self) -> bool:
        return ~self.crc5 == 0x0c


    def crc16_reset(self) -> None:
        self.crc16 = 0xffff

    def crc16_add(self, bit: bool) -> None:
        crc16 = self.crc16
        # 1bit input, right shifting
        lsb = (crc16 & 1) != 0
        crc16 = crc16 >> 1
        if bit != lsb:
            crc16 ^= 0xa001	# b10100000 00000001
        self.crc16 = crc16

    def crc16_valid(self) -> bool:
        return ~self.crc16 == 0x800d


    async def send_crc5(self) -> int:
        crc5_inverted = ~self.crc5 & 0x1f
        await self.send_data(crc5_inverted, 5)
        return self.crc5

    async def send_crc16(self) -> int:
        crc16_inverted = ~self.crc16 & 0xffff
        await self.send_data(crc16_inverted, 16)
        return self.crc16

    def validate_pid(self, pid: int) -> None:
        assert pid & ~0xff == 0, f"pid = {pid} is out of 8-bit range"
        assert (~pid >> 4 & 0xf) == pid & 0xf, f"pid = {pid} is out of 8-bit range"

    def validate_token(self, token: int) -> None:
        assert token & ~0xf == 0, f"token = {token} is out of 4-bit range"

    def validate_frame(self, frame: int) -> None:
        assert frame & ~0x7ff == 0, f"frame = {frame} is out of 11-bit range"

    def validate_addr(self, addr: int) -> None:
        assert addr & ~0x7f == 0, f"addr = {addr} is out of 7-bit range"

    def validate_endp(self, endp: int) -> None:
        assert endp & ~0xf == 0, f"endp = {endp} is out of 4-bit range"

    def validate_addr_endp(self, addr: int, endp: int) -> None:
        self.validate_addr(addr)
        self.validate_endp(endp)

    def resolve_addr(self, addr: int = None) -> int:
        if addr is None:
            print("resolve_addr({}) = {}".format(addr, self.addr))
            return self.addr
        self.validate_addr(addr)
        return addr

    def resolve_endp(self, endp: int = None) -> int:
        if endp is None:
            print("resolve_endp({}) = {}".format(endp, self.endp))
            return self.endp
        self.validate_endp(endp)
        return endp

    async def send_pid(self, pid: int = None, token: int = None) -> None:
        if pid is None:
            self.validate_token(token)
            print("send_pid(pid={}, token={})".format(pid, token))
            pid = ((~token << 4) & 0xf0) | token
            print("send_pid(token={:x}) computed PID = {} {:02x}".format(token, pid, pid))

        self.validate_pid(pid)
        print("send_pid() sending = {} {:02x}".format(token, pid, pid))
        await self.send_data(pid, 8)

        # Should be equivalent to
        #await self.send_data(token, 4)
        #await self.send_data(~token, 4)

    async def send_crc5_payload(self, token: int, data: int, crc5: int = None) -> None:
        self.validate_token(token)
        assert data & ~0x7ff == 0, f"data = {data:x} is out of 11-bit range"

        await self.send_sync()
        await self.send_pid(token=token)
        self.crc5_reset()
        await self.send_data(data, 11)
        if crc5 is None:
            await self.send_crc5()
        else:
            crc5_inverted = ~self.crc5 & 0x1f
            if crc5 != crc5_inverted:
                self.dut._log.warning(f"crc5 mismatch (provided) {crc5:02x} != {crc5_inverted:02x} (computed) {self.crc5:02x} (actual)")
            assert crc5 & ~0x1f == 0, f"crc5 = {crc5:02x} is out of 5-bit range"
            await self.send_data(crc5, 5)	# we send the one provided in argument
        await self.send_eop()

    async def send_token(self, token: int, addr: int = None, endp: int = None, crc5: int = None) -> None:
        addr = self.resolve_addr(addr)
        endp = self.resolve_endp(endp)
        data = endp << 7 | addr
        await self.send_crc5_payload(token, data, crc5)

    async def send_handshake(self, token: int) -> None:
        self.validate_token(token)
        assert token == self.ACK or token == self.NACK or token == self.STALL, f"send_handshake(token={token}) is not ACK, NACK or STALL type"
        await self.send_sync()
        await self.send_pid(token=token)
        await self.send_eop()

    async def send_sof(self, frame: int, crc5: int = None) -> None:
        self.validate_frame(frame)
        await self.send_crc5_payload(self.SOF, frame, crc5)

    async def send_crc16_payload(self, token: int, payload: Payload, crc16: int = None) -> None:
        self.validate_token(token)
        await self.send_sync()
        await self.send_pid(token=token)
        self.crc16_reset()
        await self.send_payload(payload)
        if crc16 is None:
            await self.send_crc16()
        else:
            crc16_inverted = ~self.crc16 & 0xffff
            if crc16 != crc16_inverted:
                self.dut._log.warning(f"crc16 mismatch (provided) {crc16:04x} != {crc16_inverted:04x} (computed) {self.crc16:04x} (actual)")
            assert crc16 & ~0xffff == 0, f"crc16 = {crc16:04x} is out of 16-bit range"
            await self.send_data(crc16, 16)	# we send the one provided in argument
        await self.send_eop()

    async def send_payload(self, payload: Payload) -> int:
        for v in payload:
            await self.send_data(v, 8)
        return len(payload)

    async def send_out_data0(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        # FIXME make payload a class
        await self.send_token(self.OUT, addr, endp)
        await self.send_crc16_payload(self.DATA0, payload, crc16)
        self.data0 = False

    async def send_out_data1(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        # FIXME make payload a class
        await self.send_token(self.OUT, addr, endp)
        await self.send_crc16_payload(self.DATA1, payload, crc16)
        self.data0 = True

    async def send_out_data(self, payload: Payload, addr: int = None, endp: int = None, crc16: int = None) -> None:
        if self.data0:
            await self.send_out_data0(payload, addr, endp, crc16)
        else:
            await self.send_out_data1(payload, addr, endp, crc16)


