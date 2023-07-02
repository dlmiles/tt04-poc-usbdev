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

from test_setup import USBDEV, REG_FRAME
from test_tt2wb import TT2WB, extract_bit
import RomReader


def try_integer(v, default_value=None):
    if type(v) is int:
        return v
    if v.is_resolvable:
        return v.integer
    if default_value is not None:
        return default_value
    return v

def try_binary(v, width=None):
    if type(v) is BinaryValue:
        return v
    if type(v) is str:
        return v
    if width is None:
        return BinaryValue(v)
    else:
        return BinaryValue(v, n_bits=width)




# Useful when you want a particular format, but only if it is a number
#  try_decimal_format(valye, '3d')
def try_decimal_format(v, fmt=None):
    #print("try_decimal_format(v={} {}, fmt={} {})".format(v, type(v), fmt, type(fmt)))
    if fmt is not None and type(v) is int:
        fmtstr = "{{0:{}}}".format(fmt)
        #print("try_decimal_format(v={} {}, fmt={} {})  fmtstr=\"{}\" => \"{}\"".format(v, type(v), fmt, type(fmt), fmtstr, fmtstr.format(v)))
        return fmtstr.format(v)
    return "{}".format(v)

def try_compare_equal(a, b):
    a_s = str(try_binary(a))	# string
    b_s = str(try_binary(b))
    rv = a_s == b_s
    #print("{} {} == {} {} => {}".format(a, a_s, b, b_s, rv))
    return rv

def try_name(v):
    if v is None:
        return None
    if hasattr(v, '_name'):
        return v._name
    return str(v)

def try_path(v):
    if v is None:
        return None
    if hasattr(v, '_path'):
        return v._path
    return str(v)

def try_value(v):
    if v is None:
        return None
    if hasattr(v, 'value'):
        return v.value
    return str(v)

def report_resolvable(dut, pfx = None, node = None, depth = None, filter = None):
    if depth is None:
        depth = 3
    if depth < 0:
        return
    if node is None:
        node = dut
        if pfx is None:
            pfx = "DUT."
    if pfx is None:
        pfx = ""
    for design_element in node:
        if isinstance(design_element, cocotb.handle.ModifiableObject):
            if filter is None or filter(design_element._path, design_element._name):
                dut._log.info("{}{} = {}".format(pfx, design_element._name, design_element.value))
        elif isinstance(design_element, cocotb.handle.HierarchyObject) and depth > 0:
            report_resolvable(dut, pfx + try_name(design_element) + '.', design_element, depth=depth - 1, filter=filter)	# recurse
        else:
            if filter is None or filter(design_element._path, design_element._name):
                dut._log.info("{}{} = {} {}".format(pfx, try_name(design_element), try_value(design_element), type(design_element)))
    pass


# Does not nest
def design_element_internal(dut_or_node, name):
    #print("design_element_internal(dut_or_node={}, name={})".format(dut_or_node, name))
    for design_element in dut_or_node:
        #print("design_element_internal(dut_or_node={}, name={}) {} {}".format(dut_or_node, name, try_name(design_element), design_element))
        if design_element._name == name:
            return design_element
    return None

# design_element(dut, 'module1.module2.signal')
def design_element(dut, name):
    names = name.split('.')	# will return itself if no dot
    #print("design_element(name={}) {} len={}".format(name, names, len(names)))
    node = dut
    for name in names:
        node = design_element_internal(node, name)
        if node is None:
            return None
    return node

def design_element_exists(dut, name):
    return design_element(dut, name) is not None


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


EP_COUNT = 2
ADDRESS_LENGTH = 68
MAX_PACKET_LENGTH = 40

@cocotb.test()
async def test_usbdev(dut):
    dut._log.info("start")
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())

    dumpvars = ['CI', 'GL_TEST', 'FUNCTIONAL', 'USE_POWER_PINS', 'SIM', 'UNIT_DELAY', 'SIM_BUILD', 'GATES', 'ICARUS_BIN_DIR', 'COCOTB_RESULTS_FILE', 'TESTCASE', 'TOPLEVEL']
    if 'CI' in os.environ and os.environ['CI'] == 'true':
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

    ttwb = TT2WB(dut)



    await ttwb.exe_reset()

    await ttwb.exe_enable()

    await ttwb.idle()

    await ttwb.exe_disable()

    await ttwb.idle()

    await ttwb.exe_enable()

    await ttwb.exe_write(0x1234, 0xfedcba98)
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
        else:
            end_of_buffer = a
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

    usbdev = USBDEV(dut, ttwb)

    await usbdev.setup()

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(0xff00, 4)
    await ttwb.wb_dump(0xff04, 4)
    await ttwb.wb_dump(0xff08, 4)
    await ttwb.wb_dump(0xff0c, 4)
    await ttwb.wb_dump(0xff10, 4)
    await ttwb.wb_dump(0xff20, 4)

    # Perform reset sequence
    #reset_seq = [0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    #await send_sequence_in8(dut, reset_seq)

    await ClockCycles(dut.clk, 256)

    PHY_CLK_FACTOR = 8	# 4 per edge
    OVERSAMPLE = 4
    TICKS_PER_BIT = PHY_CLK_FACTOR * OVERSAMPLE

    # FIXME why are both the WriteEnable high for output at startup

    # TODO work out how to get the receiver started
    #  for a start writeEnable of DP&DM is set
    dut.uio_in.value = dut.uio_in.value | 0x08	# POWER bit3
    await ClockCycles(dut.clk, 128)

    usb = NRZI(dut, TICKS_PER_BIT = TICKS_PER_BIT)

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


    # FIXME fetch out before and check ATTACHED
    # FIXME fetch out before and check POWERED
    # FIXME fetch out 'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string' == 'ACTIVE_INIT'  011b

    await ClockCycles(dut.clk, TICKS_PER_BIT)
    
    ##############################################################################################

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

    # ADDR=0000001b
    await usb.send_1()  # LSB0
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

    # CRC5=11101b 0x1d
    await usb.send_1()  # LSB0
    await usb.send_0()
    await usb.send_1()
    await usb.send_1()
    await usb.send_1()  # MSB4

    # EOP  SE0 SE0 J IDLE
    await usb.send_SE0()
    await usb.send_SE0()
    await usb.send_J()
    await usb.send_idle()

    # FIXME check state machine for error

    # Inject noise into the signals, clock/1

    # Inject noise into the signals, clock/2

    # Inject noise into the signals, clock/4

    # Inject valid packet, clock/4

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(0xff00, 4)
    await ttwb.wb_dump(0xff04, 4)
    await ttwb.wb_dump(0xff08, 4)
    await ttwb.wb_dump(0xff0c, 4)
    await ttwb.wb_dump(0xff10, 4)
    await ttwb.wb_dump(0xff20, 4)


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



# NRZI - 0 = transition
# NRZI - 1 = no transition
# NRZI - stuff 0 after 6 111111s
class NRZI():
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

    def nrzi(self, whoami: str):
        assert(whoami == 'J' or whoami == 'K')
        if(self.nrzi_last != whoami):
            self.nrzi_one_count = 0
        else:
            self.nrzi_one_count += 1
        self.nrzi_last = whoami
        if self.nrzi_one_count >= 6:
            if whoami == 'J':
                self.send_K()
            else:
                self.send_J()

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
        self.nrzi('J')

    async def send_K(self) -> None:
        if self.LOW_SPEED:
            await self.update(self.LS_K)
        else:
            await self.update(self.HS_K)
        self.nrzi('K')

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

    async def send_idle(self) -> None:
        if self.LOW_SPEED:
            await self.update(self.LS_J)	# aka IDLE
        else:
            await self.update(self.HS_J)	# aka IDLE
        self.reset('J')
