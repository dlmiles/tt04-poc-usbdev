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
from usbtester.TT2WB import *
from usbtester.UsbDevDriver import *
from usbtester.UsbBitbang import *
from usbtester.Payload import *
import usbtester.RomReader


from test_tt2wb import test_tt2wb_raw, test_tt2wb_cooked


DATAPLUS_BITID		= 0
DATAMINUS_BITID		= 1
INTERRUPTS_BITID	= 2
POWER_BITID		= 3


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
    # The rx_timerLong constants that specify counter units to achieve USB
    #  specification wall-clock timing requirements based on the 48MHz phyCd_clk.
    #
    # resume   HOST instigated, reverse polarity for > 20ms, then a LS EOP.
    #            reverse polarity to what? (does this mean FS/LS)
    #            LS EOP has a specific polarity
    #          DEVICE instigated (optional), send K state for >1ms and <15ms.
    #            Can only be starte after being idle >5ms
    #               (check how this interacts with suspend state)
    #            Host will respond within 1ms (I assume from not sending K state)
    #          Timer 0xe933f looks to be 19.899ms @48MHz
    #
    # reset    HOST send SE0 for >= 10ms, DEVICE may notice after 2.5us
    #          Timer 0x7403f looks to be 9.899ms @48MHz
    #
    # suspend  HOST send IDLE(J) for >= 3ms, is a suspend condition.
    #          This is usually inhibited by SOF(FS) or KeepAlive/EOP(LS) every 1ms.
    #          Timer 0x21fbf looks to be 2.899ms @48MHz
    #
    # The SIM values are 1/200 to speed up simulation testing.
    #
    # We have something in the GHA CI to patch this matter (ensure the production values are put back) with 'sed -i'.
    #
    # PRODUCTION
    # -  assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0e933f);
    # -  assign rx_timerLong_reset = (rx_timerLong_counter == 23'h07403f);
    # -  assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h021fbf);
    # SIM (FS 1/200)
    #    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h0012a7);
    #    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h000947);
    #    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h0002b7);
    # SIM (LS 1/25),
    #          tried at 1/40 but it is on the limit of firing a spurious suspend from specification packet
    #          sizes with not enough gap between tests to allow us to setup testing comfortably
    #    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h00953f);
    #    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h004a3f);
    #    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h0015bf);
    #
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


def signal_interrupts(dut) -> bool:
    return extract_bit(dut.uio_out, INTERRUPTS_BITID)


def signal_power_change(dut, bf: bool) -> bool:
    return change_bit(dut.uio_in, POWER_BITID, bf)


FSM = {
    'main':      'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string',
    'active':    'dut.usbdev.ctrl.ctrl_logic.active_stateReg_string',
    'token':     'dut.usbdev.ctrl.ctrl_logic.token_stateReg_string',
    'rx_packet': 'dut.usbdev.ctrl.phy_logic.rx_packet_stateReg_string',
    'tx_frame':  'dut.usbdev.ctrl.phy_logic.tx_frame_stateReg_string'
}


def fsm_signal_path(label: str) -> str:
    if label in FSM:
        return FSM[label]
    raise Exception(f"Unable to find fsm_signal: {label}")


def fsm_printable(signal: cocotb.handle.NonHierarchyObject) -> str:
    assert isinstance(signal, cocotb.handle.NonHierarchyObject)
    value = signal.value
    if value.is_resolvable and signal._path.endswith('_string'):
        # Convert to string
        return value.buff.decode('ascii').rstrip()
    else:
        return str(value.value)


def fsm_state(dut, label: str) -> str:
    path = fsm_signal_path(label)

    signal = design_element(dut, path)
    if signal is None:
        raise Exception(f"Unable to find signal path: {path}")

    return fsm_printable(signal)


def fsm_state_expected(dut, label: str, expected: str) -> bool:
    state = fsm_state(dut, label)
    assert state == expected, f"fsm_state({label}) in state {state} expected state {expected}"
    return True


## FIXME see if we can register multiple items here (to speed up simulation?) :
##   signal, prefix/label, lambda on change, lambda on print
##  want to have some state changes lookup another signal to print
@cocotb.coroutine
def monitor(dut, path: str, prefix: str = None) -> None:
    value = None

    signal = design_element(dut, path)
    if signal is None:
        raise Exception(f"Unable to find signal path: {path}")
        
    pfx = prefix if(prefix) else path

    value = signal.value
    dut._log.info("monitor({}) = {} [STARTED]".format(pfx, fsm_printable(signal)))

    while True:
        # in generator-based coroutines triggers are yielded
        yield ClockCycles(dut.clk, 1)
        new_value = signal.value
        if new_value != value:
            s = fsm_printable(signal)
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

    # The DUT uses a divider from the master clock at this time
    # USB spec has a (FS) 2,500ppm and (LS) 15,000ppm timing requirement
    #
    # 192MHz = 5208.333ps  (48MHzx4)  this is 1/15624 out
    #
    clock = Clock(dut.clk, 5208, units="ps")	# 5208.3333  192MHz
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


    debug(dut, '001_TT2WB_RAW')
    await test_tt2wb_raw(dut)

    debug(dut, '002_TT2WB_COOKED')
    await test_tt2wb_cooked(dut)


    # Start these now as they will fire during USB interface RESET sequence
    # Defered the other FSM monitors setup due to significant simulation slowdown
    await cocotb.start(monitor(dut, 'dut.usbdev.interrupts',                               'interrupts'))
    await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string',     'main'))

    debug(dut, '003_WISHBONE')

    ttwb = TT2WB(dut)


    await ttwb.exe_reset()

    await ttwb.exe_enable()

    await ttwb.exe_idle()

    await ttwb.exe_disable()

    await ttwb.exe_idle()

    await ttwb.exe_enable()

    await ttwb.exe_write(addr=0x1234, data=0xfedcba98)
    # test write cycle over WB
    await ttwb.exe_write(addr=0xff80, data=0xff80fe7f)
    # test write cycle over WB

    v = await ttwb.exe_read(0x0000)
    # v == xxxxxxxx (uninit mem inside usbdev)

    await ttwb.exe_idle()

    await ttwb.exe_write(addr=0x0000, data=0x76543210)

    v = await ttwb.exe_read(0x0000)
    assert(v == 0x76543210), f"unexpected readback of WB_READ(0x0000) = 0x{v:x} (expected 0x76543210)"


    await ttwb.exe_write(addr=0x0000, data=0x00000000)

    v = await ttwb.exe_read(0x0000)
    assert(v == 0x00000000), f"unexpected readback of WB_READ(0x0000) = 0x{v:x} (expected 0x00000000)"

    await ttwb.exe_disable()

    await ttwb.exe_reset()

    debug(dut, '003_WISHBONE_PROBE')

    await ttwb.exe_enable()

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)

    for a in range(0, ADDRESS_LENGTH+1, 4):
        i = a & 0xff
        d = ((i+3) << 24) | ((i+2) << 16) | ((i+1) << 8) | (i)
        await ttwb.exe_write(d, a)

    # This is probing the wishbone address space to find the end of the memory buffer
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

    debug(dut, '003_WISHBONE_ZERO')

    for a in range(0, ADDRESS_LENGTH+1, 4):	# zero out memory buffer
        await ttwb.exe_write(0x00000000, a)

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

    #############################################################################################

    await ClockCycles(dut.clk, 256)

    LOW_SPEED = True #False

    PHY_CLK_FACTOR = 4	# 2 per edge
    OVERSAMPLE = 4	# 48MHz / 12MHz
    TICKS_PER_BIT = PHY_CLK_FACTOR * OVERSAMPLE if(not LOW_SPEED) else PHY_CLK_FACTOR * OVERSAMPLE * 8

    # Why are both the WriteEnable high for output at startup ?  With both D+/D- low.  SE0 condx
    dut._log.info("{} = {}".format(dut.dut.usb_dm_write._path, str(dut.dut.usb_dm_write.value)))
    dut._log.info("{} = {}".format(dut.dut.usb_dm_writeEnable._path, str(dut.dut.usb_dm_writeEnable.value)))
    dut._log.info("{} = {}".format(dut.dut.usb_dp_write._path, str(dut.dut.usb_dp_write.value)))
    dut._log.info("{} = {}".format(dut.dut.usb_dp_writeEnable._path, str(dut.dut.usb_dp_writeEnable.value)))
    #assert dut.dut.usb_dm_write.value == 0, f"{dut.dut.usb_dm_write._path} = {str(dut.dut.usb_dm_write.value)}"
    assert dut.dut.usb_dm_writeEnable.value == 0
    #assert dut.dut.usb_dp_write.value == 0
    assert dut.dut.usb_dp_writeEnable.value == 0

    if LOW_SPEED:
        await ttwb.wb_write(REG_CONFIG, 0x00000040)	# bit6 LOW_SPEED
        await ClockCycles(dut.clk, TICKS_PER_BIT)	# not sure if needed FIXME test this

    ## Check FSM(main) state currently is ATTACHED
    assert fsm_state_expected(dut, 'main', 'ATTACHED')

    # Receiver started for a start writeEnable of DP&DM is set
    signal_power_change(dut, True)	# POWER uio_in bit3

    await ClockCycles(dut.clk, 4)	# to let FSM update

    ## Check FSM(main) state goes to POWERED
    assert fsm_state_expected(dut, 'main', 'POWERED')

    await ClockCycles(dut.clk, 128)

    usb = UsbBitbang(dut, TICKS_PER_BIT = TICKS_PER_BIT, LOW_SPEED=False) #LOW_SPEED)

    debug(dut, '010_RESET')

    #############################################################################################
    # Reset 10ms (ok this sequence works but takes too long to simulate, for test/debug)
    #
    # To speed it up the verilog can be built with 1/200 reduced rx_timerLong constants
    #
    # So this section detects and confirms how it was built and prevents the wrong values
    #  making it to production.
    #
    await usb.send_SE0()	# !D+ bit0 !D- bit1 = SE0 RESET

    # FIXME
    reset_ticks = int((48000000 / 100) * PHY_CLK_FACTOR)	# 48MHz for 10ms

    ## auto-detect and also

    ##egrep "rx_timerLong_reset =" UsbDeviceTop.v # 23'h07403f ## FULL
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h07403f"):
        ticks = reset_ticks	## ENABLE

    ## egrep "rx_timerLong_reset =" UsbDeviceTop.v ## 23'h000947  1/200 FS (default SIM speedup)
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h000947"):
        ticks = int(reset_ticks / 200)	## ENABLE 1/200th
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SIM-MODE-200th (USB FULL_SPEED test mode) = {}".format(reset_ticks, ticks))
        if 'CI' in os.environ and os.environ['CI'] == 'true':
            dut._log.warning("You are building GDS for production but are using UsbDeviceTop.v with simulation modified timer values".format(reset_ticks, ticks))
            exit(1)	## failure ?

    ##                                             ## 23'h004a3f  1/25  LS
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h004a3f"):
        ticks = int(reset_ticks / 25)	## ENABLE 1/25th
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SIM-MODE-25th (USB LOW_SPEED test mode) = {}".format(reset_ticks, ticks))
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
        await ClockCycles(dut.clk, int(ticks % PER_ITER)+1)	# just in case there is a remainder
    elif ticks > 0:
        await ClockCycles(dut.clk, ticks)
    else:
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SKIPPED".format(reset_ticks))

    # REG_INTERRUPT also has 0x0001000 set for RESET
    v = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert v & INTR_RESET != 0, f"REG_INTERRUPT expected to see: RESET bit set"
    await ttwb.wb_write(REG_INTERRUPT, INTR_RESET, regwr)	# W1C
    v = await ttwb.wb_read(REG_INTERRUPT, regrd)
    if v & INTR_RESET != 0:
        dut._log.warning("REG_INTERRUPT expected to see: RESET bit clear {:08x}".format(v))
    assert v & INTR_RESET == 0, f"REG_INTERRUPT expected to see: RESET bit clear"

    # FIXME understand the source of this interrupt (it seems RESET+DISCONNECT are raised at the same time)
    # REG_INTERRUPT also has 0x0010000 set for DISCONNECT
    assert v & INTR_DISCONNECT != 0, f"REG_INTERRUPT expected to see: DISCONNECT bit set"
    await ttwb.wb_write(REG_INTERRUPT, INTR_DISCONNECT, regwr)	# W1C
    v = await ttwb.wb_read(REG_INTERRUPT, regrd)
    if v & INTR_DISCONNECT != 0:
        dut._log.warning("REG_INTERRUPT expected to see: DISCONNECT bit clear {:08x}".format(v))
    assert v & INTR_DISCONNECT == 0, f"REG_INTERRUPT expected to see: DISCONNECT bit clear"

    assert v == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{v:08x}"

    ## Check FSM(main) state goes to ACTIVE_INIT
    assert fsm_state_expected(dut, 'main', 'ACTIVE_INIT')

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

    debug(dut, '020_SETUP_BITBANG')

    await usb.send_idle()

    ## Check FSM(main) state goes to ACTIVE
    assert fsm_state_expected(dut, 'main', 'ACTIVE')

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

    # When the hardware does this we insert 2 bit times here (if we should be sending now)
    # But accept a tolerance of upto 24 bit times for the rx to become active
    # The 15 interations appear to be the limit before we start failing, the timing maybe
    #  between the end of the SE0 condition (from EOP), until the rx decode a character, so
    #  iterations are lost to allow for decode of the SYNC.
    gap_limit = 15 if(LOW_SPEED) else 14
    for i in range(0, gap_limit):	# LOW_SPEED=15 FULL_SPEED=14
        await usb.send_idle()		# This demonstrates maximum tolerance at for TOKEN<>DATA gap


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


    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)

    debug(dut, '020_SETUP_BITBANG_TX_ACK')

    await ClockCycles(dut.clk, TICKS_PER_BIT*19)	# FIXME wait for auto ACK


    # FIXME check state machine for error (move these tests noise/corruption tests to another suite)
    # Checking state machine ERROR indication and recovery

    # Inject noise into the signals, clock/1

    # Inject noise into the signals, clock/2

    # Inject noise into the signals, clock/4 (these start to look like real random data bits)

    # Inject valid packet after noise (at various lengths), check for success,
    #  if not retry valid packet, expect 1st packet maybe to work, but 2nd packet to always work, confirming retransmission, clock/4
    
    # Inject valid looking SYNC sequence then noise at various lengths
    # Send packet, maybe it worked, if not retransmit, confirm by now it always worked


    # FIXME write helper to check TX busy and wait idle (dont but now manage ability test observed states seen, and states never seen, to provide test true/false result)
    # Wait for TX of SYNC+ACK  (0x80 + 0xd2)
    
    # FIXME here the hardware auto ACKed the SETUP (see above, but validate data in certain states for example PID=ACK)

    # FIXME perform SETUP SET_ADDRESS to non-zero and switch for the remainer of the tests below
    # FIXME this better tests realworld expectations
    
    # FIXME test addr/endp filter rejection (after the addr setup and switch check filter)

    debug(dut, '020_SETUP_BITBANG_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*16)	# gap to next test

    ADDRESS = 0x000
    ENDPOINT = 0x0

    ####
    #### 004 SETUP no data
    ####

    debug(dut, '050_SETUP_TOKEN')

    # mimic a 12byte IN payload delivered over 2 packets
    # setup device to respond to IN for addr=0x000 endp=0x0 with 8 bytes of payload

    await driver.halt(endp=ENDPOINT) # HALT EP=0
    await ttwb.wb_write(BUF_DESC0, desc0(code=DESC0_INPROGRESS))
    await ttwb.wb_write(BUF_DESC1, desc1(length=8))
    await ttwb.wb_write(BUF_DESC2, desc2(direction=DESC2_OUT, interrupt=True))
    await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0), max_packet_size=20))
    await driver.unhalt(endp=ENDPOINT)

    await usb.send_token(usb.SETUP, addr=ADDRESS, endp=ENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
    debug(dut, '051_SETUP_DATA0')
    setup = (0x04030201, 0x08070605) # crc16=0x304f
    await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
    await usb.send_idle()

    # FULL_SPEED=17 LOW_SPEED=129
    await ClockCycles(dut.clk, int((TICKS_PER_BIT/2)+1))	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+1=17
    ## Manage interrupt and reset
    assert signal_interrupts(dut) == True, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
    assert data & INTR_EP0SETUP != 0, f"REG_INTERRUPT expects EP0SETUP to fire {v:08x}"
    await ttwb.wb_write(REG_INTERRUPT, INTR_EP0SETUP, regdesc)
    data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
    assert data & INTR_EP0SETUP == 0, f"REG_INTERRUPT expects EP0SETUP to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert signal_interrupts(dut) == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"

    # Validate 8 bytes of SETUP made it into the buffer location
    data = await ttwb.wb_read(REG_SETUP0, regdesc)
    assert data == setup[0], f"SETUP0 expected to see: SETUP payload+0 0x{setup[0]:08x} is 0x{v:08x}"
    data = await ttwb.wb_read(REG_SETUP1, regdesc)
    assert data == setup[1], f"SETUP1 expected to see: SETUP payload+4 0x{setup[1]:08x} is 0x{v:08x}"

    debug(dut, '052_SETUP_ACK')

    # FIXME check tx_state cycles and emits ACK
    await ClockCycles(dut.clk, TICKS_PER_BIT*24)	# let TX run auto ACK

    debug(dut, '053_SETUP_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*16)	# gap to next test

    ####
    #### 005  EP0 with IN (enumeration device-to-host response)
    ####

    debug(dut, '060_EP0_IN')

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

    debug(dut, '061_EP0_IN_TX_DATA0')
    
    # FIXME assert we saw request
    

    await ClockCycles(dut.clk, TICKS_PER_BIT*8*13)	## wait for TX to finish
    await ClockCycles(dut.clk, TICKS_PER_BIT*3)

    # FIXME inject delay here to confirm timer limits against spec

    debug(dut, '062_EP0_IN_RX_ACK')
    await usb.send_handshake(usb.ACK)	# host ACKing
    await usb.send_idle()

    await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for TX to finish

    # Originally the interrupt did not fire just because the buffer was full.
    # The the implementation expected the software to over provision a buffer size at least 1 byte longer, but
    #  but to 16 byte granularity that 1 byte turns into 16 which isn't good for a resource constrained environments.
    #
    # IMHO That should an allowed condition, to fill the buffer exactly.
    # The hardware has dataRxOverrun detection which is a proper reason for it not to fire,
    #  it also has a mode desc.completionOnFull which should be more appropiately renamed to desc.completionOnOverrun
    #  but IMHO it should at least mark an error occured that is visible to the driver.
    #
    assert signal_interrupts(dut) == True, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {v:08x}"
    await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert signal_interrupts(dut) == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"


    data = await ttwb.wb_read(REG_EP0, regrd)
    assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
    data = await ttwb.wb_read(BUF_DESC0, lambda v,a: desc0_format(v))
    assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
    ## code=SUCCESS
    assert data & 0x000f0000 == 0x00000000, f"DESC0 expected code={data:08x}"
    data = await ttwb.wb_read(BUF_DESC1, lambda v,a: desc1_format(v))
    data = await ttwb.wb_read(BUF_DESC2, lambda v,a: desc2_format(v))
    ## FIXME This was successful, but error handling indication to CPU could be better

    debug(dut, '063_EP0_IN_END')

    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### 006  EP0 with OUT (enumeration host-to-device command)
    ####

    debug(dut, '070_EP0_OUT')

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

    debug(dut, '071_EP0_OUT_RX_DATA0')

    payload = (0xfbfaf9f8, 0xfffefdfc)
    await usb.send_crc16_payload(usb.DATA0, Payload.int32(*payload))	# host sends OUT calling for data
    await usb.send_idle()

    await ClockCycles(dut.clk, 17)	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+1=17
    assert signal_interrupts(dut) == True, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {v:08x}"
    await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {v:08x}"
    assert data == 0, f"REG_INTERRUPT expects all clear {v:08x}"
    assert signal_interrupts(dut) == False, f"interrupts = {str(dut.dut.interrupts.value)} unexpected state"

    data = await ttwb.wb_read(REG_EP0, regrd)
    assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
    data = await ttwb.wb_read(BUF_DESC0, lambda v,a: desc0_format(v))
    assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
    assert data & 0x000f0000 == 0x00000000, f"DESC0 expected code={data:08x}"
    data = await ttwb.wb_read(BUF_DESC1, lambda v,a: desc1_format(v))
    data = await ttwb.wb_read(BUF_DESC2, lambda v,a: desc2_format(v))

    # Validate 8 bytes of PAYLOAD made it into the buffer location
    data = await ttwb.wb_read(BUF_DATA0)
    assert data == payload[0], f"PAYLOAD0 expected to see: payload+0 0x{payload[0]:08x} is 0x{v:08x}"
    data = await ttwb.wb_read(BUF_DATA1)
    assert data == payload[1], f"PAYLOAD1 expected to see: payload+4 0x{payload[1]:08x} is 0x{v:08x}"

    debug(dut, '072_EP0_OUT_TX_ACK')

    ## FIXME validate the PID=ACK auto-tx here
    await ClockCycles(dut.clk, TICKS_PER_BIT*24)	## let TX run auto ACK

    debug(dut, '073_EP0_OUT_END')

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
    debug(dut, '100_IN_NAK')

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

    debug(dut, '101_IN_NACK_TX_NACK')
    ## FIXME observe automatic NACK from hardware (as no descriptor is setup) but endpoint enabled
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)
    await ClockCycles(dut.clk, TICKS_PER_BIT*12)

    debug(dut, '102_IN_NACK_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)

    ####
    #### 011
    ####

    ## interrupt ACK
    debug(dut, '110_IN_ACK')

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


    debug(dut, '111_IN_ACK_TX_ACK')
    ## FIXME observe automatic ACK with data
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)
    await ClockCycles(dut.clk, TICKS_PER_BIT*12)

    debug(dut, '112_IN_ACK_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*64)

    ## FIXME confirm the hardwre is capable of auto-arming the same data
    ##   without the need for CPU interrupts, without the need for CPU to update
    ##   any EP or DESC, so that the CPU only needs to update the data area
    ##   (potentially between HALT/UNHALT) as necessary



    ## FIXME check why after send_idle() (or really send_eop()) the line state does not look like FS idle (DP high, DM low)
    ##   this is a matter of the cocotb testing code not the DUT


    ## FIXME check the tristate of the process really do mute the input when WE.
    ##   as the RX is always running it would be problematic to see our own TX data back on the RX


    ## FIXME observe DATA0/DATA1 generation (not here, move that test)


    ### FIXME large packets
    ### FIXME too large packets (> endp.max_packet_size)
    ### FIXME large packets with heavy bit-stuffing (USB spec test patterns ?)



    ### FIXME IN with zero-length payload, ACK/NACK/STALL (device response)

    ### FIXME OUT with zero-length payload, or device sends NACK/STALL, and host ACK (host response)


    ### FIXME IN with isochronous (confirm no ACKs)
    ### FIXME OUT with isochronous (confirm no ACKs)

    ### FIXME test the ctrl/phy clocks can both be 48MHz, then try slower/faster/much-faster ctrl clocks

    ####
    #### Never seen a SOF frame since reset so
    ####

    debug(dut, '800_SOF_frameValid_0')

    data = await ttwb.wb_read_BinaryValue(REG_FRAME)	# 12'b0xxxxxxxxxxx
    assert extract_bit(data[0], 12) == False, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=0"

    ####
    #### SOF token with frame 0
    ####

    debug(dut, '810_SOF_0000')

    frame = 0
    data = await ttwb.wb_read(REG_FRAME, regrd)	# 12'b0xxxxxxxxxxx
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
    assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

    debug(dut, '811_SOF_0000_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### SOF token with frame 1
    ####

    debug(dut, '820_SOF_0001')

    frame = 1
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
    assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

    debug(dut, '821_SOF_0001_END')
    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### SOF token with frame 2047
    ####

    debug(dut, '830_SOF_2047')

    frame = 2047
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
    assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

    debug(dut, '831_SOF_2047_END')
    #await ClockCycles(dut.clk, TICKS_PER_BIT*32)
    # minimal delay, confirm back-to-back decoding works

    ####
    #### SOF token with frame 42
    ####

    debug(dut, '840_SOF_0042')

    frame = 42
    data = await ttwb.wb_read(REG_FRAME, regrd)
    await usb.send_sof(frame=frame)
    await usb.send_idle()
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
    assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

    debug(dut, '841_SOF_0042_END')
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

