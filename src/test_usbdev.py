#!/usr/bin/python3
#
#
#  Interesting environment settings:
#
#	CI=true		(validates expected production timer settings, implies ALL=true)
#	ALL=true	Run all tests (not the default profile to help speed up development)
#	DEBUG=true	Enable cocotb debug logging level
#	LOW_SPEED=true	Test hardware in USB LOW_SPEED mode (1.5 Mbps), FULL_SPEED mode is the default
#			Tests take longer to run as wall-clock time is longer due to slower speed of USB
#
#
#
import os
import sys
import re
import inspect
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles
from cocotb.wavedrom import trace
from cocotb.binary import BinaryValue
from cocotb.utils import get_sim_time

from usbtester import *
from usbtester.cocotbutil import *
from usbtester.cocotb_proxy_dut import *
from usbtester.TT2WB import *
from usbtester.UsbDevDriver import *
from usbtester.UsbBitbang import *
from usbtester.SignalAccessor import *
from usbtester.Payload import *
#from usbtester.FSM import *
from usbtester.SignalOutput import *


from test_tt2wb import test_tt2wb_raw, test_tt2wb_cooked


DATAPLUS_BITID		= 0	# bidi: uio_out & uio_in
DATAMINUS_BITID		= 1	# bidi: uio_out & uio_in
INTERRUPTS_BITID	= 2	# output: uio_out
POWER_BITID		= 3	# input: uio_in


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
    r'[\./]pwrgood_',
    r'[\./]ANTENNA_',
    r'[\./]clkbuf_leaf_',
    r'[\./]clknet_leaf_',
    r'[\./]clkbuf_[\d_]+_clk',
    r'[\./]clknet_[\d_]+_clk',
    r'[\./]net\d+[\./]',
    r'[\./]net\d+$',
    r'[\./]fanout\d+[\./]',
    r'[\./]fanout\d+$',
    r'[\./]input\d+[\./]',
    r'[\./]input\d+$',
    r'[\./]hold\d+[\./]',
    r'[\./]hold\d+$'
]
EXCLUDE_RE = dict(map(lambda k: (k,re.compile(k)), exclude))

def exclude_re_path(path: str, name: str):
    for v in EXCLUDE_RE.values():
        if v.search(path):
            #print("EXCLUDED={}".format(path))
            return False
    return True

# This is used as detection of gatelevel testing, with a flattened HDL,
#  we can only inspect the external module signals and disable internal signal inspection.
def resolve_GL_TEST():
    gl_test = False
    if 'GL_TEST' in os.environ:
        gl_test = True
    if 'GATES' in os.environ and os.environ['GATES'] == 'yes':
        gl_test = True
    return gl_test


def run_this_test(default_value: bool = True) -> bool:
    if 'CI' in os.environ and os.environ['CI'] != 'false':
        return True	# always on for CI
    if 'ALL' in os.environ and os.environ['ALL'] != 'false':
        return True
    return default_value


def resolve_LOW_SPEED():
    low_speed = False
    if 'LOW_SPEED' in os.environ:
        low_speed = True
    return low_speed


def usb_spec_wall_clock_tolerance(value: int, LOW_SPEED: bool) -> tuple:
    freq = 1500000 if(LOW_SPEED) else 12000000
    ppm = 15000 if(LOW_SPEED) else 2500

    variation = (freq * ppm) / 1000000
    varfactor = variation / freq

    tolmin = int(value - (value * varfactor))
    tolmax = int(value + (value * varfactor))

    return (tolmin, tolmax)


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
    # SIM (LS 1/20 current)
    #          tried at 1/25 but it is on the limit of firing a spurious suspend from specification packet
    #          sizes with not enough gap between tests to allow us to setup testing comfortably
    #    assign rx_timerLong_resume = (rx_timerLong_counter == 23'h00ba8f);
    #    assign rx_timerLong_reset = (rx_timerLong_counter == 23'h005ccf);
    #    assign rx_timerLong_suspend = (rx_timerLong_counter == 23'h001b2f);
    # SIM (LS 1/25 old)
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


async def wait_for_signal_interrupts(dut, not_after: int = None, not_before: int = None) -> int:
    limit = not_after if(not_after is not None) else sys.maxsize
    count = 0
    bf = signal_interrupts(dut)
    while not bf and count < limit:
        count += 1
        await ClockCycles(dut.clk, 1)
        bf = signal_interrupts(dut)

    if bf and not_before is not None:
        assert count >= not_before, f"wait_for_signal_interrupts(not_after={not_after}, not_before={not_before}) = NOT_BEFORE failed at count={count} too early"

    if not_after is not None:
        # Find out when it would have triggered and report
        tmp = count
        while not bf and tmp < limit + 1000:
            tmp += 1
            await ClockCycles(dut.clk, 1)
            bf = signal_interrupts(dut)
        msg = f"(signal fired at {tmp})" if(bf) else f"(signal did not fire by {tmp})"
        assert count <= not_after, f"wait_for_signal_interrupts(not_after={not_after}, not_before={not_before}) = NOT_AFTER failed at count={count} too late {msg}"

    dut._log.warning(f"wait_for_signal_interrupts(not_after={not_after}, not_before={not_before}) = PASS count={count} bf={bf}")

    return count if(bf) else -1


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


# signal: NonHierarchyObject|BinaryValue
def fsm_printable(signal) -> str:
    is_string = False
    if isinstance(signal, cocotb.handle.NonHierarchyObject):
        is_string = signal._path.endswith('_string')
        value = signal.value
    assert isinstance(value, BinaryValue)
    if value.is_resolvable and is_string: # and signal._path.endswith('_string'):
        # Convert to string
        return value.buff.decode('ascii').rstrip()
    else:
        return str(value)


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
## signal: str|SignalAccessor
@cocotb.coroutine
def monitor(dut, signal, prefix: str = None) -> None:
    value = None

    if isinstance(signal, str):
        signal = SignalAccessor(dut, signal)
    assert isinstance(signal, SignalAccessor)
    #signal = design_element(dut, path)
    #if signal is None:
    #    raise Exception(f"Unable to find signal path: {path}")
        
    pfx = prefix if(prefix) else signal.path

    value = signal.value
    value_str = str(value)
    dut._log.info("monitor({}) = {} [STARTED]".format(pfx, fsm_printable(signal.raw)))

    while True:
        # in generator-based coroutines triggers are yielded
        yield ClockCycles(dut.clk, 1)
        new_value = signal.value
        new_value_str = str(new_value)
        if new_value_str != value_str:
            s = fsm_printable(signal.raw)
            dut._log.info("monitor({}) = {}".format(pfx, s))
            value = new_value
            value_str = new_value_str


## FIXME fix the cocotb timebase for 100MHz and 48MHz (or 192MHz and 48MHz initially - done)
## FIXME add assert to confirm elapsed realtime
## FIXME test the ctrl/phy clocks can both be 48MHz, then try slower/faster/much-faster ctrl clocks

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
    CLOCK = 192000000
    CLOCK_MHZ = CLOCK / 1000000
    clock = Clock(dut.clk, 5208, units="ps")	# 5208.3333  192MHz
    cocotb.start_soon(clock.start())

    dumpvars = ['CI', 'GL_TEST', 'FUNCTIONAL', 'USE_POWER_PINS', 'SIM', 'UNIT_DELAY', 'SIM_BUILD', 'GATES', 'ICARUS_BIN_DIR', 'COCOTB_RESULTS_FILE', 'TESTCASE', 'TOPLEVEL', 'DEBUG', 'LOW_SPEED']
    if 'CI' in os.environ and os.environ['CI'] != 'false':
        for k in os.environ.keys():
            if k in dumpvars:
                dut._log.info("{}={}".format(k, os.environ[k]))

    depth = None
    GL_TEST = resolve_GL_TEST()
    if GL_TEST:
        dut._log.info("GL_TEST={} (detected)".format(GL_TEST))
        #depth = 1

    if GL_TEST:
        dut = ProxyDut(dut)

    report_resolvable(dut, 'initial ', depth=depth, filter=exclude_re_path)

    validate(dut)

    if GL_TEST and 'RANDOM_POLICY' in os.environ:
        await ClockCycles(dut.clk, 1)		## crank it one tick, should assign some non X states
        if os.environ['RANDOM_POLICY'] == 'zero' or os.environ['RANDOM_POLICY'].lower() == 'false':
            ensure_resolvable(dut, policy=False, filter=exclude_re_path)
        elif os.environ['RANDOM_POLICY'] == 'one' or os.environ['RANDOM_POLICY'].lower() == 'true':
            ensure_resolvable(dut, policy=True, filter=exclude_re_path)
        else: # if os.environ['RANDOM_POLICY'] == 'random':
            ensure_resolvable(dut, policy='random', filter=exclude_re_path)

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
    signal_accessor_interrupts = SignalAccessor(dut, 'uio_out', INTERRUPTS_BITID)	# dut.usbdev.interrupts
    await cocotb.start(monitor(dut, signal_accessor_interrupts, 'interrupts'))
    if not GL_TEST:
        await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.main_stateReg_string',      'main'))

    # This is a custom capture mechanism of the output encoding
    # Goals:
    #         dumping to a text file and making a comparison with expected output
    #         confirming period where no output occured
    #         confirm / measure output duration of special conditions
    #
    SO = SignalOutput(dut)
    # FIXME check this is attached to the PHY_clk
    signal_accessor_usb_dp_write = SignalAccessor(dut, 'uio_out', DATAPLUS_BITID)	# dut.usb_dp_write
    signal_accessor_usb_dm_write = SignalAccessor(dut, 'uio_out', DATAMINUS_BITID)	# dut.usb_dm_write
    await cocotb.start(SO.register('so', signal_accessor_usb_dp_write, signal_accessor_usb_dm_write))
    # At startup in sumlation we see writeEnable asserted and so output
    SO.assert_resolvable_mode(True)
    SO.assert_encoded_mode(SO.SE0)

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

    for a in range(0, ADDRESS_LENGTH+4, 4):	# 4 bytes too far into undefined space
        i = a & 0xff
        d = ((i+3) << 24) | ((i+2) << 16) | ((i+1) << 8) | (i)
        await ttwb.exe_write(d, a)

    # This is probing the wishbone address space to find the end of the memory buffer
    end_of_buffer = -1
    for a in range(0, ADDRESS_LENGTH+4, 4):
        i = a & 0xff
        expect = ((i+3) << 24) | ((i+2) << 16) | ((i+1) << 8) | (i)
        d = await ttwb.exe_read_BinaryValue(a)
        if d[0].is_resolvable:
            # The probe strategy might see aliasing of memory locations (gatelevel/flattened HDL might see this)
            if a >= ADDRESS_LENGTH and d[0] != expect:
                dut._log.warning("MEM-BUF-ALIAS detected ? @0x{:04x} actual={:08x} expected={:08x}".format(a, d[0].integer, expect))
                if end_of_buffer == -1:
                    end_of_buffer = a
            else:
                assert d[0] == expect, f"read at {a} expected {expect:08x} got {d[0]} {d[0].integer:08x}"
        elif end_of_buffer == -1:
            end_of_buffer = a	# stop at first non resolvable
    dut._log.info("END_OF_BUFFER = 0x{:04x} {}d".format(end_of_buffer, end_of_buffer))
    assert ADDRESS_LENGTH == end_of_buffer, f"ADDRESS_LENGTH does not match detected END_OF_BUFFER {ADDRESS_LENGTH} != {end_of_buffer}"

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

    await driver.poweron()
    await driver.do_config_global_enable(True)
    await driver.initialize_hardware()
    await driver.do_config_interrupt_enable(True)

    ## FIXME need to understand/define power on expectations
    if not GL_TEST:
        SO.assert_resolvable_mode()		# disable checking (simulation)
    SO.assert_encoded_mode()		# disable checking

    await driver.do_config_pullup(True)

    # FIXME we should provide SO visibility on OE bits
    if GL_TEST:
        SO.assert_resolvable_mode(True)		# 0 state outputs
        SO.assert_encoded_mode(SO.DM)		# 0 state outputs (gatelevel)
        SO.assert_resolvable_mode()	# FIXME disable this for GL_TEST
        SO.assert_encoded_mode()	# FIXME disable this for GL_TEST
    else:
        SO.assert_resolvable_mode(False)	# x state outputs
        SO.assert_encoded_mode(SO.X)		# x state outputs (simulation)

    await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
    await ttwb.wb_dump(REG_FRAME, 4)
    await ttwb.wb_dump(REG_ADDRESS, 4)
    await ttwb.wb_dump(REG_INTERRUPT, 4)
    await ttwb.wb_dump(REG_HALT, 4)
    await ttwb.wb_dump(REG_CONFIG, 4)
    await ttwb.wb_dump(REG_INFO, 4)

    #############################################################################################

    await ClockCycles(dut.clk, 256)

    LOW_SPEED = resolve_LOW_SPEED() # False for FULL_SPEED (default), or True for LOW_SPEED
    SPEED_MODE = 'LOW_SPEED' if(LOW_SPEED) else 'FULL_SPEED'

    PHY_CLK_FACTOR = 4	# 2 per edge
    OVERSAMPLE = 4	# 48MHz / 12MHz
    TICKS_PER_BIT = PHY_CLK_FACTOR * OVERSAMPLE if(not LOW_SPEED) else PHY_CLK_FACTOR * OVERSAMPLE * 8

    if not GL_TEST:
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
        # FIXME consider separate control bit for TIP inversion (D+/D-) at this time that is linked

    if not GL_TEST:	## Check FSM(main) state currently is ATTACHED
        assert fsm_state_expected(dut, 'main', 'ATTACHED')


    v = dut.uio_in.value
    nv = v & ~(1 << POWER_BITID)
    dut._log.warning("POWER_BITID POWER_BITID={} {} bv={} v={} nv={}".format(POWER_BITID, 1 << POWER_BITID, str(dut.uio_in.value), str(v), str(nv)))

    # Receiver started for a start writeEnable of DP&DM is set
    signal_power_change(dut, True)	# POWER uio_in bit3

    v = dut.uio_in.value
    nv = v & ~(1 << POWER_BITID)
    dut._log.warning("POWER_BITID POWER_BITID={} {} bv={} v={} nv={}".format(POWER_BITID, 1 << POWER_BITID, str(dut.uio_in.value), str(v), str(nv)))


    await ClockCycles(dut.clk, 4)	# to let FSM update

    if not GL_TEST:    ## Check FSM(main) state goes to POWERED
        assert fsm_state_expected(dut, 'main', 'POWERED')

    await ClockCycles(dut.clk, 128)

    usb = UsbBitbang(dut, TICKS_PER_BIT = TICKS_PER_BIT, LOW_SPEED = LOW_SPEED)

    debug(dut, '010_RESET')

    #############################################################################################
    # Reset 10ms (ok this sequence works but takes too long to simulate, for test/debug)
    #
    # To speed it up the verilog can be built with 1/200 reduced rx_timerLong constants
    #
    # So this section detects and confirms how it was built and prevents the wrong values
    #  making it to production.
    #
    await usb.send_SE0()		# !D+ bit0 !D- bit1 = SE0 RESET

    elapsed_start = get_sim_time(units='us')

    reset_ticks = int((48000000 / 100) * PHY_CLK_FACTOR)	# 48MHz for 10ms

    # It doesn't matter which timerLong is setup in ther verilog,
    # It only matters we can detected which and know sim_timerLong_factor
    # Then apply FS or LS testing requirements

    ## auto-detect and also
    (tolmin, tolmax) = usb_spec_wall_clock_tolerance(10000, LOW_SPEED)	# USB host-to-device reset is 10ms
    dut._log.info("USB host-to-device signalling reset specification target is 10000us  min={} max={} after ppm clock tolerance {}".format(tolmin, tolmax, SPEED_MODE))

    sim_timerLong_factor = 1
    ##egrep "rx_timerLong_reset =" UsbDeviceTop.v # 23'h07403f ## FULL
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h07403f"):
        ticks = reset_ticks	## ENABLE

    ## egrep "rx_timerLong_reset =" UsbDeviceTop.v ## 23'h000947  1/200 FS (default SIM speedup)
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h000947"):
        sim_timerLong_factor = 200
        ticks = int(reset_ticks / sim_timerLong_factor)	## ENABLE 1/200th
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SIM-MODE-timerLong-200xspeedup (USB FULL_SPEED test mode) = {}".format(reset_ticks, ticks))
        if 'CI' in os.environ and os.environ['CI'] != 'false':
            dut._log.warning("You are building GDS for production but are using UsbDeviceTop.v with simulation modified timer values".format(reset_ticks, ticks))
            exit(1)	## failure ?

    ##                                             ## 23'h004a3f  1/20  LS
    if grep_file('UsbDeviceTop.v', "rx_timerLong_reset =", "23\'h005ccf"):
        sim_timerLong_factor = 20
        ticks = int(reset_ticks / sim_timerLong_factor)	## ENABLE 1/20th
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SIM-MODE-timerLong-20xspeedup (USB LOW_SPEED test mode) = {}".format(reset_ticks, ticks))
        if 'CI' in os.environ and os.environ['CI'] != 'false':
            dut._log.warning("You are building GDS for production but are using UsbDeviceTop.v with simulation modified timer values".format(reset_ticks, ticks))
            exit(1)	## failure ?

    # At this time if we are GL_TEST then that is always with production system values
    if GL_TEST:
        sim_timerLong_factor = 1
        ticks = reset_ticks		## FORCE PRODUCTION
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) GL_TEST mode forces PRODUCTION test mode = {}".format(reset_ticks, ticks))

    if ticks > 0:
        PER_ITER = 38400
        await clockcycles_with_progress(dut, ticks, PER_ITER,
            lambda t: "RESET ticks = {} of {} {:3d}%".format(t, ticks, int((t / ticks) * 100.0)),
            lambda t: "RESET ticks = {} @{}MHz speedup=x{} ({}-per-iteration)".format(ticks, CLOCK_MHZ, sim_timerLong_factor, PER_ITER)
        )
    else:
        dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SKIPPED".format(reset_ticks))

    ## FIXME we want to know elapsed when interrupt triggered to confirm it is < tolmin and within a %
    #elapsed_after_factor_for_interrrupt = fsm_interrupt()

    elapsed_finish = get_sim_time(units='us')
    elapsed = elapsed_finish - elapsed_start
    elapsed_after_factor = elapsed * sim_timerLong_factor
    # We need to trigger our reset detection somewhere close to the minimum (tolmin)
    # But allow the implementation to work and be compatible with a time exceeding maximum (tolmax)

    (tolmin, tolmax) = usb_spec_wall_clock_tolerance(10000, LOW_SPEED)	# USB host-to-device reset is 10ms
    dut._log.info("ELAPSED = {:7f} x {} = {}us  (USB reset spec is 10000us  min={} max={})".format(elapsed, sim_timerLong_factor, elapsed_after_factor, tolmin, tolmax))

    # FIXME this assert should replace elapsed_after_factor with elapsed_after_factor_for_interrrupt
    #assert elapsed_after_factor < tolmin, f"USB RESET wall-clock elapsed is too short {elapsed_after_factor} > {tolmin}"
    #assert elapsed_after_factor > tolmax, f"USB RESET wall-clock elapsed is too long {elapsed_after_factor} > {tolmax}"

    assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"

    # REG_INTERRUPT also has 0x0001000 set for RESET
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_RESET != 0, f"REG_INTERRUPT expected to see: RESET bit set"
    await ttwb.wb_write(REG_INTERRUPT, INTR_RESET, regwr)	# W1C
    data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    assert data & INTR_RESET == 0, f"REG_INTERRUPT expected to see: RESET bit clear"

    # FIXME understand the source of this interrupt (it seems RESET+DISCONNECT are raised at the same time)
    # FIXME ok understood, it is due to 'pullup/power' falling edge ?
    # REG_INTERRUPT also has 0x0010000 set for DISCONNECT
    #assert data & INTR_DISCONNECT != 0, f"REG_INTERRUPT expected to see: DISCONNECT bit set"
    #await ttwb.wb_write(REG_INTERRUPT, INTR_DISCONNECT, regwr)	# W1C
    #data = await ttwb.wb_read(REG_INTERRUPT, regrd)
    #assert data & INTR_DISCONNECT == 0, f"REG_INTERRUPT expected to see: DISCONNECT bit clear"

    assert data == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{data:08x}"

    assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

    if not GL_TEST:	## Check FSM(main) state goes to ACTIVE_INIT
        assert fsm_state_expected(dut, 'main', 'ACTIVE_INIT')

    ## LS mode is setup by IDLE state D- assertion
    ## HS mode (default) is setup by IDLE state D+ assertion
    ## FS mode needs a K-chirp for 1ms just after host RESET, then readback of K-J within 100us lasting 50us
    #     need to understand the 3-K-J chirp rule, if that is the chirp sequence repeats without timeframes

    await ClockCycles(dut.clk, TICKS_PER_BIT)

    ##############################################################################################

    # These were defered so speed up the RESET simulation part
    if not GL_TEST:
        await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.phy_logic.rx_packet_stateReg_string', 'rx_packet'))
        await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.phy_logic.tx_frame_stateReg_string',  'tx_frame'))
        await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.active_stateReg_string',   'active'))
        await cocotb.start(monitor(dut, 'dut.usbdev.ctrl.ctrl_logic.token_stateReg_string',    'token'))
    
    ##############################################################################################

    if GL_TEST:		#### FLUSH states through CC
        MYADDRESS = 0
        MYENDPOINT = 0
        ## The purpose of this section is to fire traffic through CC primitives so the values conveyed lose their X states
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)		## FIXME GL_TEST debug remove me

        debug(dut, '020_GL_TEST_FLUSH')
        await usb.send_idle()

        await usb.send_token(usb.SETUP, addr=MYADDRESS, endp=MYENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
        debug(dut, '021_GL_TEST_FLUSH_DATA0')
        setup = (0x04030201, 0x08070605) # crc16=0x304f
        await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
        await usb.set_idle()
        await ClockCycles(dut.clk, TICKS_PER_BIT*23)	## Tx auto ACK

        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        await ttwb.wb_write(REG_INTERRUPT, reg_interrupt(all=True), regwr)	# UVM=W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## IDLE

        await usb.send_idle()

        await usb.send_token(usb.SETUP, addr=MYADDRESS, endp=MYENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
        debug(dut, '022_GL_TEST_FLUSH_DATA0')
        setup = (0x04030201, 0x08070605) # crc16=0x304f
        await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
        await usb.set_idle()
        await ClockCycles(dut.clk, TICKS_PER_BIT*23)	## Tx auto ACK

        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        await ttwb.wb_write(REG_INTERRUPT, reg_interrupt(all=True), regwr)	# UVM=W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## IDLE

        await usb.send_idle()

        await usb.send_token(usb.SETUP, addr=MYADDRESS, endp=MYENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
        debug(dut, '022_GL_TEST_FLUSH_DATA0')
        setup = (0x04030201, 0x08070605) # crc16=0x304f
        await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
        await usb.set_idle()
        await ClockCycles(dut.clk, TICKS_PER_BIT*23)	## Tx auto ACK

        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        await ttwb.wb_write(REG_INTERRUPT, reg_interrupt(all=True), regwr)	# UVM=W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## IDLE

        debug(dut, '023_GL_TEST_FLUSH_END')

    ##############################################################################################

    if run_this_test(True):
        debug(dut, '020_SETUP_BITBANG')

        await usb.send_idle()

        if not GL_TEST:           ## Check FSM(main) state goes to ACTIVE
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
        if GL_TEST:	# FIXME debug can remove
            gap_limit -= 4
        for i in range(0, gap_limit):	# LOW_SPEED=15 FULL_SPEED=14
            await usb.send_idle()		# This demonstrates maximum tolerance at for TOKEN<>DATA gap


        await usb.send_sync()    # SYNC 8'b00000001 0x80 KJKJKJKK

        # DATA0 PID=8'b1100_0011 0xc3
        await usb.send_pid(pid=0xc3)

        setup = (0x04030201, 0x08070605, 0x304f)
        #setup = (0x00000000, 0x00000000, 0xf4bf)
        #setup = (0xffffffff, 0xffffffff, 0x70fe)
        await usb.send_data(setup[0], 32)	# DATA[0..3]
        await usb.send_data(setup[1])		# DATA[4..7]

        await usb.send_data(setup[-1], 16, "CRC16")	# CRC16

        await usb.send_eop()	# EOP - SE0 SE0 J
        await usb.set_idle()

        SO.assert_resolvable_mode()		# disable checking
        SO.assert_encoded_mode()		# disable checking
        # FIXME This is how we want this API to work
        SO.mark_open_at_transition(f"021_SETUP_BITBANG_TX_ACK", -1)

        debug(dut, '021_SETUP_BITBANG_TX_ACK')
        await ClockCycles(dut.clk, TICKS_PER_BIT*23)	# FIXME wait for auto ACK

        # FIXME This is how we want this API to work
        SO.mark_close_same_state(TICKS_PER_BIT)
        if not GL_TEST:
            SO.assert_resolvable_mode(False)	# x state outputs
            SO.assert_encoded_mode(SO.X)		# x state outputs

        FIXME_GL_TEST_TICKS = int((TICKS_PER_BIT/2)+(TICKS_PER_BIT*7))
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)		## FIXME GL_TEST debug remove me

        debug(dut, '022_SETUP_BITBANG_CHECK')
        ## Manage interrupt and reset
        assert await wait_for_signal_interrupts(dut, int(TICKS_PER_BIT/2+FIXME_GL_TEST_TICKS)) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0SETUP != 0, f"REG_INTERRUPT expected to see: EP0SETUP bit set"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0SETUP, regwr)	# UVM=W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0SETUP == 0, f"REG_INTERRUPT expected to see: EP0SETUP bit clear"
        assert data == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{data:08x}"

        # FIXME check where this DESC0/EP0 was setup and what do, is it no ZEROed out here ?
        # FIXME test what the hardware does after power on, reset, with respect to the host trying to communicate
        # FIXME STALL for SETUP is a special case ?
        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0x00000000,         f"DESC0.offset expected to see: 0 {data:08x}"
        assert data & 0x000f0000 == 0x000f0000,         f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,         f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,         f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 20 << 16,           f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,         f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,         f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,         f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00000000,         f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,         f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,         f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,         f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,         f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,         f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000008,         f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,         f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,         f"ENDP.isochronous not as expected {data:08x}"
        mpl = MAX_PACKET_LENGTH << 22
        mpl = 20 << 22	# 5 = 10100	# FIXME where does this 20 come from ?
        assert data & 0xffc00000 == mpl,                f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,         f"ENDP.unused not as expected {data:08x}"

        # Validate 8 bytes of SETUP made it into the buffer location
        data = await ttwb.wb_read(REG_SETUP0, regrd)
        assert data == setup[0], f"SETUP0 expected to see: SETUP payload+0 0x{setup[0]:08x} is 0x{data:08x}"
        data = await ttwb.wb_read(REG_SETUP1, regrd)
        assert data == setup[1], f"SETUP1 expected to see: SETUP payload+4 0x{setup[1]:08x} is 0x{data:08x}"


        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)


        debug(dut, '020_SETUP_BITBANG_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*16)	# gap to next test


    SO.unregister()


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

    ADDRESS = 0x00
    ADDRESS_ALT = 0x00
    ENDPOINT = 0x0
    ENDPOINT_ALT = 0x1	# can not be EP0

    ####
    #### 050 SETUP no data
    ####

    if run_this_test(True):
        debug(dut, '050_SETUP_TOKEN')

        # mimic a 12byte IN payload delivered over 2 packets
        # setup device to respond to IN for addr=0x000 endp=0x0 with 8 bytes of payload

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=8))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=20))
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.SETUP, addr=ADDRESS, endp=ENDPOINT, crc5=0x02) # explicit crc5 for a0/ep0
        debug(dut, '051_SETUP_DATA0')
        setup = (0x04030201, 0x08070605) # crc16=0x304f
        await usb.send_crc16_payload(usb.DATA0, Payload.int32(*setup), crc16=0x304f) # explicit crc16
        await usb.set_idle()

        # FULL_SPEED=18 LOW_SPEED=130+4 (was 64)
        wfi_limit = int((TICKS_PER_BIT/2)+2) if(LOW_SPEED) else int(TICKS_PER_BIT/2)
        assert await wait_for_signal_interrupts(dut, wfi_limit) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # FIXME remove this now we have wait_for_signal_interrupts()
        #await ClockCycles(dut.clk, int((TICKS_PER_BIT/2)+2))	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+2=18
        #if LOW_SPEED:
        #    await ClockCycles(dut.clk, 4+16+16+16+12)	# CI need +4 more then local here ?
        #await ClockCycles(dut.clk, TICKS_PER_BIT)	# added since aLen=96

        ## Manage interrupt and reset
        data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
        assert data & INTR_EP0SETUP != 0, f"REG_INTERRUPT expects EP0SETUP to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0SETUP, regdesc)
        data = await ttwb.wb_read(REG_INTERRUPT, regdesc)
        assert data & INTR_EP0SETUP == 0, f"REG_INTERRUPT expects EP0SETUP to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate 8 bytes of SETUP made it into the buffer location
        data = await ttwb.wb_read(REG_SETUP0, regdesc)
        assert data == setup[0], f"SETUP0 expected to see: SETUP payload+0 0x{setup[0]:08x} is 0x{data:08x}"
        data = await ttwb.wb_read(REG_SETUP1, regdesc)
        assert data == setup[1], f"SETUP1 expected to see: SETUP payload+4 0x{setup[1]:08x} is 0x{data:08x}"

        debug(dut, '052_SETUP_ACK')

        SO.assert_resolvable_mode()		# disable checking
        SO.assert_encoded_mode()		# disable checking

        # FIXME check tx_state cycles and emits ACK
        await ClockCycles(dut.clk, TICKS_PER_BIT*24)	# let TX run auto ACK

        debug(dut, '053_SETUP_END')

        await ClockCycles(dut.clk, TICKS_PER_BIT*16)	# gap to next test


    ####
    #### 060  EP0 with IN (enumeration device-to-host response)
    ####

    if run_this_test(True):
        debug(dut, '060_EP0_IN')

        # Setup driver with data in buffer and expect the driver to manage sending
        # For example as a response to SETUP
        await driver.halt(endp=ENDPOINT)
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=8))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_20, 0x14131211)
        await ttwb.wb_write(BUF_DATA1_20, 0x18171615)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)	# host sents IN calling for data
        await usb.set_idle()

        debug(dut, '061_EP0_IN_TX_DATA0')

        # FIXME assert we saw request


        await ClockCycles(dut.clk, TICKS_PER_BIT*8*13)	## wait for TX to finish
        await ClockCycles(dut.clk, TICKS_PER_BIT*3)

        # FIXME inject delay here to confirm timer limits against spec

        debug(dut, '062_EP0_IN_RX_ACK')
        await usb.send_handshake(usb.ACK)	# host ACKing
        await usb.set_idle()

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for TX to finish

        debug(dut, '063_EP0_IN_CHECK')
        # Originally the interrupt did not fire just because the buffer was full.
        # The the implementation expected the software to over provision a buffer size at least 1 byte longer, but
        #  but to 16 byte granularity that 1 byte turns into 16 which isn't good for a resource constrained environments.
        #
        # IMHO That should an allowed condition, to fill the buffer exactly.
        # The hardware has dataRxOverrun detection which is a proper reason for it not to fire,
        #  it also has a mode desc.completionOnFull which should be more appropiately renamed to desc.completionOnOverrun
        #  but IMHO it should at least mark an error occured that is visible to the driver.
        #
        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"


        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
        ## code=SUCCESS
        assert data & 0x000f0000 == 0x00000000, f"DESC0 expected code={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        ## FIXME This was successful, but error handling indication to CPU could be better

        debug(dut, '064_EP0_IN_END')

        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### 070  EP0 with OUT (enumeration host-to-device command)
    ####

    if run_this_test(True):
        debug(dut, '070_EP0_OUT')

        # Setup driver with data in buffer and expect the driver to manage receiving
        # For example as a response to SETUP
        await driver.halt(endp=ENDPOINT)
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=8))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        #await ttwb.wb_write(BUF_DATA0_20, 0x94939291)
        #await ttwb.wb_write(BUF_DATA1_20, 0x97969594)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.OUT, addr=ADDRESS, endp=ENDPOINT)	# host sents IN calling for data

        debug(dut, '071_EP0_OUT_RX_DATA0')

        payload = (0xfbfaf9f8, 0xfffefdfc)
        await usb.send_crc16_payload(usb.DATA0, Payload.int32(*payload))	# host sends OUT calling for data
        await usb.set_idle()

        await ClockCycles(dut.clk, 17)	# SIM delay to allow waiting-for-interrupt (TICKS_PER_BIT/2)+1=17
        if LOW_SPEED:
            await ClockCycles(dut.clk, 7*16)
        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000008 != 0, f"REG_EP0 expected dataPhase to be updated {data:08x}"
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x000003ff == 8, f"DESC0 expected offset to be 8"
        assert data & 0x000f0000 == 0x00000000, f"DESC0 expected code={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))

        # Validate 8 bytes of PAYLOAD made it into the buffer location
        data = await ttwb.wb_read(BUF_DATA0_20)
        assert data == payload[0], f"PAYLOAD0 expected to see: payload+0 0x{payload[0]:08x} is 0x{data:08x}"
        data = await ttwb.wb_read(BUF_DATA1_20)
        assert data == payload[1], f"PAYLOAD1 expected to see: payload+4 0x{payload[1]:08x} is 0x{data:08x}"

        debug(dut, '072_EP0_OUT_TX_ACK')

        ## FIXME validate the PID=ACK auto-tx here
        await ClockCycles(dut.clk, TICKS_PER_BIT*24)	## let TX run auto ACK

        debug(dut, '073_EP0_OUT_CHECK')

        debug(dut, '074_EP0_OUT_END')

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
    #### 100
    ####

    if run_this_test(False):
        ## interrupt NAK
        debug(dut, '100_IN_NAK')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        # FIXME randomize values here, set zero, 0xfffff, random to confirm DESC[012] contents do not matter (run the test 3 times)
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=False, completionOnFull=True))
        # the key things for auto NAK generation are enable=True and head=0 (no descriptor, so no data)
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(0), max_packet_size=0))
        await driver.unhalt(endp=ENDPOINT)

        # USB interrupt (host driven endpoint polling)
        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '101_IN_NAK_TX_NAK')
        ## FIXME observe automatic NAK from hardware (as no descriptor is setup) but endpoint enabled
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)


        debug(dut, '102_IN_NAK_CHECK')


        debug(dut, '103_IN_NAK_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 011
    ####

    if run_this_test(False):
        ## interrupt ACK
        debug(dut, '110_IN_ACK')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=4))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        # This time we are enable=True and head!=0 (so the DESC[012] above is important
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=4))
        await ttwb.wb_write(BUF_DATA0_20, 0x0b0a0908)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()


        debug(dut, '111_IN_ACK_TX_ACK')
        ## FIXME observe automatic ACK with data
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)


        debug(dut, '112_IN_ACK_CHECK')

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)


        debug(dut, '113_IN_ACK_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ###
    ### 300 SETUP seq
    ###




    ## FIXME confirm the hardwre is capable of auto-arming the same data
    ##   without the need for CPU interrupts, without the need for CPU to update
    ##   any EP or DESC, so that the CPU only needs to update the data area
    ##   (potentially between HALT/UNHALT) as necessary



    ## FIXME check why after send_idle()/set_idle() (or really send_eop()) the line state does not look like FS idle (DP high, DM low)
    ##   this is a matter of the cocotb testing code not the DUT


    ## FIXME check the tristate of the process really do mute the input when WE.
    ##   as the RX is always running it would be problematic to see our own TX data back on the RX


    ## FIXME observe DATA0/DATA1 generation (not here, move that test)


    ### FIXME large packets
    ### FIXME too large packets (> endp.max_packet_size)
    ### FIXME large packets with heavy bit-stuffing (USB spec test patterns ?)

    ### FIXME OUT packets for which no device buffer is ready, should generate a NAK by default ?
    ### FIXME the hardware appears to ACK data out of correct DATA PHASE, maybe it should NAK ?  but the h/w need to record this occured



    ###
    ### 500 IN with 8,16,32,64,512,1023,1024,MAX_BUFFER payload, ACK device response
    ###

    payload_lengths = []
    if run_this_test(False):
        payload_lengths = [8,16,32,64,512,1023,1024,-1]

    for payload_len in payload_lengths:
        if payload_len < 0:
            payload_len = MAX_PACKET_LENGTH

        testid = 500
        testname = f"_IN_{payload_len}"

        if payload_len > MAX_PACKET_LENGTH:
            dut._log.warning("SKIP TEST: {} wants payload_len={} which exceeds hardware design maximum {}".format(testname, payload_len, MAX_PACKET_LENGTH))
            continue

        debug(dut, f"{testid+0}{testname}")

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=payload_len))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=MAX_PACKET_LENGTH))
        # FIXME pattern fill
        payload = Payload.fill(0xff, payload_len)	# zero filled for now, good for bit-stuffing test
        count = await ttwb.wb_write_payload(BUF_DATA0_20, payload)
        assert payload_len == count
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, f"{testid+1}{testname}_TX_DATA0")
        ## FIXME observe automatic tx with payload data
        ## FIXME observe payload bytes ? and count ?
        print("payload.bit_stuff_count={} for {}".format(payload.bit_stuff_count(), payload_len))
        await ClockCycles(dut.clk, TICKS_PER_BIT * (42 + (payload_len*8) + payload.bit_stuff_count()))

        debug(dut, f"{testid+2}{testname}_RX_ACK")
        await usb.send_handshake(usb.ACK)	# host ACKing
        await usb.set_idle()

        debug(dut, f"{testid+3}{testname}_CHECK")

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == payload_len,        f"DESC0.offset expected to see: 0 {data:08x}"	# varies
        assert data & 0x000f0000 == 0x00000000,         f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,         f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,         f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == payload_len << 16,  f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,         f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,         f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,         f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,         f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,         f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,         f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,         f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,         f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,         f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000008,         f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,         f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,         f"ENDP.isochronous not as expected {data:08x}"
        mpl = MAX_PACKET_LENGTH << 22
        assert data & 0xffc00000 == mpl,                f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,         f"ENDP.unused not as expected {data:08x}"

        readpayload = await ttwb.wb_read_payload(BUF_DATA0_20, payload_len)
        assert payload_len == len(readpayload)
        assert payload.equals(readpayload), f"payload content does does not match expected"

        debug(dut, f"{testid+4}{testname}_END")
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ###
    ### 550 OUT with 8,16,32,64,512,1023,1024,MAX_BUFFER payload, ACK device response
    ###

    payload_lengths = []
    if run_this_test(False):
        payload_lengths = [8,16,32,64,512,1023,1024,-1]

    for payload_len in payload_lengths:
        if payload_len < 0:
            payload_len = MAX_PACKET_LENGTH

        testid = 550
        testname = f"_OUT_{payload_len}"

        if payload_len > MAX_PACKET_LENGTH:
            dut._log.warning("SKIP TEST: {} wants payload_len={} which exceeds hardware design maximum {}".format(testname, payload_len, MAX_PACKET_LENGTH))
            continue

        debug(dut, f"{testid+0}{testname}")

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=payload_len))
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, data_phase=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=MAX_PACKET_LENGTH))
        fill_payload = Payload.fill(0x00, payload_len)	# to check buffer is filled
        count = await ttwb.wb_write_payload(BUF_DATA0_20, fill_payload)
        assert payload_len == count
        await driver.unhalt(endp=ENDPOINT)

        payload = Payload.fill(0xff, payload_len)	# 0xff, good for bit-stuffing test
        # Note data_phase=True, do we'll send out DATA1 this time, to confirm it resets back to DATA0
        await usb.send_out_data1(payload, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, f"{testid+1}{testname}_RX_DATA0")

        debug(dut, f"{testid+2}{testname}_TX_ACK")
        ## FIXME observe automatic tx with payload data
        ## FIXME observe payload bytes ? and count ?
        print("payload.bit_stuff_count={} for {}".format(payload.bit_stuff_count(), payload_len))
        await ClockCycles(dut.clk, TICKS_PER_BIT * (50 + (payload_len*8) + payload.bit_stuff_count()))

        debug(dut, f"{testid+3}{testname}_CHECK")

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == payload_len,        f"DESC0.offset expected to see: 0 {data:08x}"	# varies
        assert data & 0x000f0000 == 0x00000000,         f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,         f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,         f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == payload_len << 16,  f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,         f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00000000,         f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,         f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,         f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,         f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,         f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,         f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,         f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,         f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000000,         f"ENDP.data_phase not as expected {data:08x}"	# test back to DATA0
        assert data & 0x0000fff0 == 0x00000000,         f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,         f"ENDP.isochronous not as expected {data:08x}"
        mpl = MAX_PACKET_LENGTH << 22
        assert data & 0xffc00000 == mpl,                f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,         f"ENDP.unused not as expected {data:08x}"

        readpayload = await ttwb.wb_read_payload(BUF_DATA0_20, payload_len)
        assert payload_len == len(readpayload)
        assert payload.equals(readpayload), f"payload content does does not match expected"

        debug(dut, f"{testid+4}{testname}_END")
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ###
    ### 600 IN with zero-length payload, ACK device response
    ###

    if run_this_test(True):
        debug(dut, '600_IN_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '601_IN_EMPTY_TX_DATA0')
        ## FIXME observe automatic tx with empty data
        ## FIXME observe payload bytes ? and count ?
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)

        debug(dut, '602_IN_EMPTY_RX_ACK')
        await usb.send_handshake(usb.ACK)	# host ACKing
        await usb.set_idle()

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for RX to finish

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x00000000,      f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,      f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000008,      f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '603_IN_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ###
    ### 610 IN with zero-length payload, NAK device response
    ###

    if run_this_test(True):
        debug(dut, '610_IN_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '611_IN_EMPTY_TX_DATA0')
        ## FIXME observe automatic tx with empty data
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)

        debug(dut, '612_IN_EMPTY_RX_NAK')
        await usb.send_handshake(usb.NAK)	# host NAKing
        await usb.set_idle()

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for RX to finish

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        # No interrupt due to NAK
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"	# clear due to NAK
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        #assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        #await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        #data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x000f0000,      f"DESC0.code expected code={data:08x}"		# TODO indication of NAK?
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,      f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000000,      f"ENDP.data_phase not as expected {data:08x}"	# FIXME check this
        assert data & 0x0000fff0 == 0x00000020,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '613_IN_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ###
    ### 620 IN with zero-length payload, STALL device response
    ###

    if run_this_test(True):
        debug(dut, '620_IN_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)
        await driver.unhalt(endp=ENDPOINT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '621_IN_EMPTY_TX_DATA0')
        ## FIXME observe automatic tx with empty data
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)

        debug(dut, '622_IN_EMPTY_RX_STALL')
        await usb.send_handshake(usb.STALL)	# host NAKing
        await usb.set_idle()

        await ClockCycles(dut.clk, TICKS_PER_BIT*8)	## wait for RX to finish

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        # No interrupt due to STALL
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"	# clear due to STALL
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        #assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        #await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        #data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x000f0000,      f"DESC0.code expected code={data:08x}"		# TODO indication of STALL?
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,      f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000000,      f"ENDP.data_phase not as expected {data:08x}"	# FIXME check this
        assert data & 0x0000fff0 == 0x00000020,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '623_IN_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 650 OUT with zero-length payload (ACK host response)
    ####

    if run_this_test(True):
        debug(dut, '650_OUT_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)	# not needed by function, only for testing buffer is filled
        await driver.unhalt(endp=ENDPOINT)

        payload = Payload.empty() 	# EMPTY
        await usb.send_out_data0(payload, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '651_OUT_EMPTY_TX_ACK')
        ## FIXME observe automatic tx for empty data
        ## FIXME observe payload bytes ? and count ?
        await ClockCycles(dut.clk, TICKS_PER_BIT*22)	## wait for TX to finish

        debug(dut, '652_OUT_EMPTY_CHECK')
        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x00000000,      f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00000000,      f"DESC2.direction not as expected {data:08x}"	# OUT
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000008,      f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '653_OUT_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 660 OUT with zero-length payload (NAK host response)
    ####

    if run_this_test(True):
        debug(dut, '660_OUT_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, nak=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8)) # NAK
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)	# not needed by function, only for testing buffer is filled
        await driver.unhalt(endp=ENDPOINT)

        payload = Payload.empty() 	# EMPTY
        await usb.send_out_data0(payload, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '661_OUT_EMPTY_TX_NAK')
        ## FIXME observe automatic tx for empty data
        ## FIXME observe payload bytes ? and count ?
        await ClockCycles(dut.clk, TICKS_PER_BIT*22)	## wait for TX to finish

        debug(dut, '662_OUT_EMPTY_CHECK')
        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x00000000,      f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# FIXME is this correct?
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00000000,      f"DESC2.direction not as expected {data:08x}"	# OUT
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000004,      f"ENDP.nak not as expected {data:08x}"		# NAK
        assert data & 0x00000008 == 0x00000008,      f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '663_OUT_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 670 OUT with zero-length payload (STALL host response)
    ####

    if run_this_test(True):
        debug(dut, '660_OUT_EMPTY')

        await driver.halt(endp=ENDPOINT) # HALT EP=0
        await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))	# EMPTY
        await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP0, reg_endp(enable=True, stall=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=8)) # STALL
        await ttwb.wb_write(BUF_DATA0_20, 0xffffffff)	# not needed by function, only for testing buffer is filled
        await driver.unhalt(endp=ENDPOINT)

        payload = Payload.empty() 	# EMPTY
        await usb.send_out_data0(payload, addr=ADDRESS, endp=ENDPOINT)
        await usb.set_idle()

        debug(dut, '661_OUT_EMPTY_TX_STALL')
        ## FIXME observe automatic tx for empty data
        ## FIXME observe payload bytes ? and count ?
        await ClockCycles(dut.clk, TICKS_PER_BIT*22)	## wait for TX to finish

        debug(dut, '662_OUT_EMPTY_CHECK')
        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"	# NOINT
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        #assert data & INTR_EP0 != 0, f"REG_INTERRUPT expects EP0 to fire {data:08x}"
        #await ttwb.wb_write(REG_INTERRUPT, INTR_EP0, regwr)
        #data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP0 == 0, f"REG_INTERRUPT expects EP0 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_20, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == 0,               f"DESC0.offset expected to see: 0 {data:08x}"	# EMPTY
        assert data & 0x000f0000 == 0x000f0000,      f"DESC0.code expected code={data:08x}"	# still INPROGRESS # TODO indication of STALL?
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_20, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00000000,      f"DESC1.length not as expected {data:08x}"	# still length=0
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_20, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00000000,      f"DESC2.direction not as expected {data:08x}"	# OUT
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP0, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000002,      f"ENDP.stall not as expected {data:08x}"		# STALL
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        assert data & 0x00000008 == 0x00000000,      f"ENDP.data_phase not as expected {data:08x}"	# still 0 (no change)
        assert data & 0x0000fff0 == 0x00000020,      f"ENDP.head not as expected {data:08x}"		# still head=0x20
        assert data & 0x00010000 == 0x00000000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"


        debug(dut, '663_OUT_EMPTY_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 700 OUT with isochronous (confirm no ACK sent by us)
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support isochronous OUT transfer, but we will test them anyway")

        # ISO should accept (receive) any data phase
        # ISO should send (transmit) only DATA0
        # So False and False would be well-formed scenario

        # These booleans allow testing with non-compliant scenarios
        # There are 4 scenarios to test represented by these 2 booleans
        expect_data_phase = False #True	# True=DATA1
        host_data_phase = False		# False=DATA0

        debug(dut, '700_ISO_OUT')

        await driver.halt(endp=ENDPOINT_ALT) # HALT EP=1
        await ttwb.wb_write(BUF_DESC0_40, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_40, desc1(length=8))
        await ttwb.wb_write(BUF_DESC2_40, desc2(direction=DESC2_OUT, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP1, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_40), data_phase=expect_data_phase, isochronous=True, max_packet_size=8))
        await ttwb.wb_write(BUF_DATA0_40, 0x00000000)	# not needed by function, only for testing buffer is filled
        await ttwb.wb_write(BUF_DATA1_40, 0x00000000)	# not needed by function, only for testing buffer is filled
        await driver.unhalt(endp=ENDPOINT_ALT)

        isopayload = Payload.int32(0x04030201, 0x08070605) # crc16=0x304f
        if host_data_phase:
            await usb.send_out_data1(isopayload, addr=ADDRESS, endp=ENDPOINT_ALT)
        else:
            await usb.send_out_data0(isopayload, addr=ADDRESS, endp=ENDPOINT_ALT)


        debug(dut, '701_ISO_OUT_NO_TX_ACK')
        ## FIXME make a delay, to then observe NO automatic ACK occured
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)
        await ClockCycles(dut.clk, TICKS_PER_BIT*12)

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP1 != 0, f"REG_INTERRUPT expects EP1 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP1, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP1 == 0, f"REG_INTERRUPT expects EP1 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_40, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == len(isopayload), f"DESC0.offset expected to see: {len(isopayload)} {data:08x}"
        assert data & 0x000f0000 == 0x00000000,      f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_40, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00080000,      f"DESC1.length not as expected {data:08x}"
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_40, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00000000,      f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP1, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        # ISO should not toggle expected next data phase
        #expected = 0x00000008 if(expect_data_phase) else 0x00000000
        expected = 0x00000008 if(host_data_phase) else 0x00000000	# Provide visibility on the data phase seen
        assert data & 0x00000008 == expected,        f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00010000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"

        # Validate 8 bytes of OUT payload made it into the buffer location
        data = await ttwb.wb_read(BUF_DATA0_40)
        assert data == isopayload.getitem32(0), f"PAYLOAD0 expected to see: payload+0 0x{isopayload.getitem32(0):08x} is 0x{data:08x}"
        data = await ttwb.wb_read(BUF_DATA1_40)
        assert data == isopayload.getitem32(1), f"PAYLOAD1 expected to see: payload+4 0x{isopayload.getitem32(1):08x} is 0x{data:08x}"


        debug(dut, '702_ISO_OUT_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)


    ####
    #### 750 IN with isochronous (confirm no ACK sent by us)
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support isochronous IN transfer, but we will test them anyway")

        # ISO should accept (receive) any data phase
        # ISO should send (transmit) only DATA0
        # So False would be well-formed scenario

        # The boolean allow testing with non-compliant scenario
        device_data_phase = False	# False=DATA0

        debug(dut, '750_ISO_IN')

        await driver.halt(endp=ENDPOINT_ALT) # HALT EP=1
        await ttwb.wb_write(BUF_DESC0_40, desc0(code=DESC0_INPROGRESS))
        await ttwb.wb_write(BUF_DESC1_40, desc1(length=8))
        await ttwb.wb_write(BUF_DESC2_40, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
        await ttwb.wb_write(REG_EP1, reg_endp(enable=True, head=addr_to_head(BUF_DESC0_40), data_phase=device_data_phase, isochronous=True, max_packet_size=8))
        isopayload = Payload.int32(0xff0201ff, 0x0055aa00)
        assert isopayload.getitem32(0) == 0xff0201ff
        assert isopayload.getitem32(1) == 0x0055aa00	# confirm API is working
        await ttwb.wb_write(BUF_DATA0_40, isopayload.getitem32(0))
        await ttwb.wb_write(BUF_DATA1_40, isopayload.getitem32(1))
        await driver.unhalt(endp=ENDPOINT_ALT)

        await usb.send_token(usb.IN, addr=ADDRESS, endp=ENDPOINT_ALT)
        await usb.set_idle()

        debug(dut, '751_ISO_IN_TX_IN')
        ## FIXME observe auto tx_state with payload
        await ClockCycles(dut.clk, TICKS_PER_BIT*102)


        debug(dut, '752_ISO_IN_NO_RX_ACK')
        ## FIXME perform a delay, to then observe NO automatic ACK occured
        await ClockCycles(dut.clk, TICKS_PER_BIT*64)
        if not LOW_SPEED or sim_timerLong_factor == 1:	# anti-SUSPEND-trigger (at 1/20 with 196MHz)
            await ClockCycles(dut.clk, TICKS_PER_BIT*12)

        await ttwb.wb_dump(0x0000, ADDRESS_LENGTH)
        await ttwb.wb_dump(REG_FRAME, 4)
        await ttwb.wb_dump(REG_ADDRESS, 4)
        await ttwb.wb_dump(REG_INTERRUPT, 4)
        await ttwb.wb_dump(REG_HALT, 4)
        await ttwb.wb_dump(REG_CONFIG, 4)
        await ttwb.wb_dump(REG_INFO, 4)

        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP1 != 0, f"REG_INTERRUPT expects EP1 to fire {data:08x}"
        await ttwb.wb_write(REG_INTERRUPT, INTR_EP1, regwr)
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_EP1 == 0, f"REG_INTERRUPT expects EP1 to clear {data:08x}"
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        # Validate expected descriptor state
        data = await ttwb.wb_read(BUF_DESC0_40, lambda v,a: desc0_format(v))
        assert data & 0x0000ffff == len(isopayload), f"DESC0.offset expected to see: {len(isopayload)} {data:08x}"
        assert data & 0x000f0000 == 0x00000000,      f"DESC0.code expected code={data:08x}"
        assert data & 0xfff00000 == 0x00000000,      f"DESC0.unused expected unused={data:08x}"
        data = await ttwb.wb_read(BUF_DESC1_40, lambda v,a: desc1_format(v))
        assert data & 0x0000fff0 == 0x00000000,      f"DESC1.next not as expected {data:08x}"
        assert data & 0xffff0000 == 0x00080000,      f"DESC1.length not as expected {data:08x}"
        assert data & 0x0000000f == 0x00000000,      f"DESC1.unused not as expected {data:08x}"
        data = await ttwb.wb_read(BUF_DESC2_40, lambda v,a: desc2_format(v))
        assert data & 0x00010000 == 0x00010000,      f"DESC2.direction not as expected {data:08x}"
        assert data & 0x00020000 == 0x00020000,      f"DESC2.interrupt not as expected {data:08x}"
        assert data & 0x00040000 == 0x00040000,      f"DESC2.completion_on_full not as expected {data:08x}"
        assert data & 0x00080000 == 0x00000000,      f"DESC2.data1_on_completion not as expected {data:08x}"
        assert data & 0xfff0ffff == 0x00000000,      f"DESC2.unused not as expected {data:08x}"

        # Validate expected endpoint register state
        data = await ttwb.wb_read(REG_EP1, regrd)
        assert data & 0x00000001 == 0x00000001,      f"ENDP.enable not as expected {data:08x}"
        assert data & 0x00000002 == 0x00000000,      f"ENDP.stall not as expected {data:08x}"
        assert data & 0x00000004 == 0x00000000,      f"ENDP.nak not as expected {data:08x}"
        # ISO should not toggle expected next data phase
        expected = 0x00000008 if(device_data_phase) else 0x00000000	# confirm no toggle
        assert data & 0x00000008 == expected,        f"ENDP.data_phase not as expected {data:08x}"
        assert data & 0x0000fff0 == 0x00000000,      f"ENDP.head not as expected {data:08x}"
        assert data & 0x00010000 == 0x00010000,      f"ENDP.isochronous not as expected {data:08x}"
        assert data & 0xffc00000 == 0x02000000,      f"ENDP.max_packet_size not as expected {data:08x}"
        assert data & 0x003e0000 == 0x00000000,      f"ENDP.unused not as expected {data:08x}"

        # Validate 8 bytes of OUT payload made it into the buffer location
        data = await ttwb.wb_read(BUF_DATA0_40)
        assert data == isopayload.getitem32(0), f"PAYLOAD0 expected to see: payload+0 0x{isopayload.getitem32(0):08x} is 0x{data:08x}"
        data = await ttwb.wb_read(BUF_DATA1_40)
        assert data == isopayload.getitem32(1), f"PAYLOAD1 expected to see: payload+4 0x{isopayload.getitem32(1):08x} is 0x{data:08x}"


        debug(dut, '753_ISO_IN_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)
        if not LOW_SPEED or sim_timerLong_factor == 1:	# anti-SUSPEND-trigger (at 1/20 with 196MHz)
            await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### Never seen a SOF frame since reset so frameValid should still be 0
    ####

    if run_this_test(True):
        debug(dut, '800_SOF_frameValid_0')

        data = await ttwb.wb_read_BinaryValue(REG_FRAME)	# 12'b0xxxxxxxxxxx
        assert extract_bit(data[0], 12) == False, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=0"


    ####
    #### SOF token with frame 0
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support SOF, but we will test them anyway")

        debug(dut, '810_SOF_0000')

        frame = 0
        data = await ttwb.wb_read(REG_FRAME, regrd)	# 12'b0xxxxxxxxxxx
        await usb.send_sof(frame=frame)
        await usb.set_idle()
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
        assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

        debug(dut, '811_SOF_0000_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### SOF token with frame 1
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support SOF, but we will test them anyway")

        debug(dut, '820_SOF_0001')

        frame = 1
        data = await ttwb.wb_read(REG_FRAME, regrd)
        await usb.send_sof(frame=frame)
        await usb.set_idle()
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
        assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

        debug(dut, '821_SOF_0001_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### SOF token with frame 2047
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support SOF, but we will test them anyway")

        debug(dut, '830_SOF_2047')

        frame = 2047
        data = await ttwb.wb_read(REG_FRAME, regrd)
        await usb.send_sof(frame=frame)
        await usb.set_idle()
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
        assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

        debug(dut, '831_SOF_2047_END')
        #await ClockCycles(dut.clk, TICKS_PER_BIT*32)
        # minimal delay, confirm back-to-back decoding works


    ####
    #### SOF token with frame 42
    ####

    if run_this_test(True):
        if LOW_SPEED:
            dut._log.warning("LOW_SPEED USB spec does not support SOF, but we will test them anyway")

        debug(dut, '840_SOF_0042')

        frame = 42
        data = await ttwb.wb_read(REG_FRAME, regrd)
        await usb.send_sof(frame=frame)
        await usb.set_idle()
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x000007ff == frame, f"SOF: frame = 0x{data:04x} is not the expected value 0x{frame:04x}"
        assert data & 0x00000800 != 0, f"SOF: frame = 0x{data:04x} is not the expected value frameValid=1"

        debug(dut, '841_SOF_0042_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### EOP idle
    ####

    keepalive = 0
    data = await ttwb.wb_read(REG_FRAME, regrd)
    assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"

    if run_this_test(True):
        debug(dut, '850_EOP_0000')

        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"

        await usb.send_eop()
        await usb.set_idle()

        debug(dut, '851_EOP_0000_CHECK')
        keepalive += 1
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)

        debug(dut, '852_EOP_0000_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### EOP idle
    ####

    if run_this_test(True):
        debug(dut, '860_EOP_0001')

        await usb.send_eop()
        await usb.set_idle()

        debug(dut, '861_EOP_0001_CHECK')
        keepalive += 1
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)

        debug(dut, '862_EOP_0001_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### EOP idle
    ####

    if run_this_test(True):
        debug(dut, '870_EOP_0002')

        await usb.send_eop()
        await usb.set_idle()

        debug(dut, '871_EOP_0002_CHECK')
        keepalive += 1
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)

        debug(dut, '872_EOP_0002_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    ####
    #### EOP idle
    ####

    if run_this_test(True):
        debug(dut, '880_EOP_0003')

        await usb.send_eop()
        await usb.set_idle()

        debug(dut, '881_EOP_0003_CHECK')
        keepalive += 1
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x07ff0000 == keepalive << 16, f"EOP: keepalive = 0x{data:04x} is not the expected value 0x{keepalive:04x}"
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)

        debug(dut, '882_EOP_0003_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)




    ####
    #### Address / Endpoint rejection test (targetting other addresses)
    ####

    addr_list = []
    if run_this_test(True):
        for endp in range(0, EP_COUNT):
            await driver.halt(endp=endp)
            await ttwb.wb_write(BUF_DESC0_20, desc0(code=DESC0_INPROGRESS))
            await ttwb.wb_write(BUF_DESC1_20, desc1(length=0))
            await ttwb.wb_write(BUF_DESC2_20, desc2(direction=DESC2_IN, interrupt=True, completionOnFull=True))
            # ensure enabled (making it more likely for a bug to show up by hardware emitting a response when it should have ignored)
            await ttwb.wb_write(REG_EP(endp), reg_endp(enable=True, head=addr_to_head(BUF_DESC0_20), max_packet_size=32))
            await driver.unhalt(endp=endp)

        addr_list = [0, 1, 2, 80, 127]

    for addr in addr_list:
        for endp in [0, 1, 15]:
            testid = 900
            testname = f"_ADDR_IGNORE_{addr:03d}:{endp:02d}"

            if addr == ADDRESS or addr == ADDRESS_ALT:
                dut._log.warning("SKIP TEST: {} wants addr={} endp={} which targets our device".format(testname, addr, endp))
                continue

            debug(dut, f"{testid+0}{testname}")

            payload_len = 8
            await usb.send_in_data(Payload.random(payload_len), addr=addr, endp=endp)
            await usb.set_idle()
            await ClockCycles(dut.clk, TICKS_PER_BIT * (16 + (payload_len * 8)))

            debug(dut, f"{testid+1}{testname}_WAIT")
            await ClockCycles(dut.clk, TICKS_PER_BIT*24)	# Where response would be

            debug(dut, f"{testid+2}{testname}_CHECK")
            ## FIXME target other addresses confirm we ignore

            data = await ttwb.wb_read(REG_INTERRUPT, regrd)
            assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
            assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"


            debug(dut, f"{testid+3}{testname}_END")
            await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### Address / Endpoint process/ignore test (targetting our device)
    ####

    addr_list = []
    if run_this_test(True):
        for endp in range(0, EP_COUNT):
            await driver.halt(endp=endp)
            # ensure disabled (we are testing it ignores)
            await ttwb.wb_write(REG_EP(endp), reg_endp(enable=False, head=addr_to_head(0), max_packet_size=0))	# DISABLE
            await driver.unhalt(endp=endp)

        addr_list = [ADDRESS, ADDRESS_ALT]

    for addr in addr_list:
        # target other endpoints confirm we ignore (enable say endp=3 confirm we NAK) disable confirm we ignore
        #
        # target other endpoint=15 (which we don't support always ignores)
        for endp in [0, 1, 2, 3, 15, -1]:
            if endp < 0:
                endp = EP_COUNT	# one more than defined in the hardware

            testid = 910
            testname = f"_ENDP_IGNORE_{addr:03d}:{endp:02d}"

            if addr != ADDRESS and addr != ADDRESS_ALT:
                dut._log.warning("SKIP TEST: {} wants addr={} endp={} which does not target our device".format(testname, addr, endp))
                continue

            debug(dut, f"{testid+0}{testname}")

            payload_len = 8
            await usb.send_in_data(Payload.random(payload_len), addr=addr, endp=endp)
            await usb.set_idle()
            await ClockCycles(dut.clk, TICKS_PER_BIT * (16 + (payload_len * 8)))

            debug(dut, f"{testid+1}{testname}_WAIT")
            await ClockCycles(dut.clk, TICKS_PER_BIT*24)	# Where response would be

            debug(dut, f"{testid+2}{testname}_CHECK")
            ## FIXME target other addresses confirm we ignore
            await ClockCycles(dut.clk, TICKS_PER_BIT*32)

            data = await ttwb.wb_read(REG_INTERRUPT, regrd)
            assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
            assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

            debug(dut, f"{testid+3}{testname}_END")
            await ClockCycles(dut.clk, TICKS_PER_BIT*32)



    ####
    #### USB host-to-device RESET signalling (after use)
    ####

    if run_this_test(True):
        debug(dut, '970_USB_RESET')

        if not GL_TEST:        ## Check FSM(main) state is currently ACTIVE
            assert fsm_state_expected(dut, 'main', 'ACTIVE')

        ## Check on entry value set for usage, to validate on exit they were cleared
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data == 0, f"REG_INTERRUPT expects all clear {data:08x}"
        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x00000800 != 0, f"REG_FRAME expects non-zero frameValid {data:08x}"
        assert data & 0x07ff0000 != 0, f"REG_FRAME expects non-zero keepaliveCount {data:08x}"


        await usb.send_SE0()	# !D+ bit0 !D- bit1 = SE0 RESET

        elapsed_start = get_sim_time(units='us')

        ## auto-detect and also
        (tolmin, tolmax) = usb_spec_wall_clock_tolerance(10000, LOW_SPEED)	# USB host-to-device reset is 10ms
        dut._log.info("USB host-to-device signalling reset specification target is 10000us  min={} max={} after ppm clock tolerance {}".format(tolmin, tolmax, SPEED_MODE))

        if ticks > 0:
            PER_ITER = 38400
            await clockcycles_with_progress(dut, ticks, PER_ITER,
                lambda t: "RESET ticks = {} of {} {:3d}%".format(t, ticks, int((t / ticks) * 100.0)),
                lambda t: "RESET ticks = {} @{}MHz speedup=x{} ({}-per-iteration)".format(ticks, CLOCK_MHZ, sim_timerLong_factor, PER_ITER)
            )
        else:
            dut._log.warning("RESET ticks = {} (for 10ms in SE0 state) SKIPPED".format(reset_ticks))

        ## FIXME we want to know elapsed when interrupt triggered to confirm it is < tolmin and within a %
        #elapsed_after_factor_for_interrrupt = fsm_interrupt()

        elapsed_finish = get_sim_time(units='us')
        elapsed = elapsed_finish - elapsed_start
        elapsed_after_factor = elapsed * sim_timerLong_factor
        # We need to trigger our reset detection somewhere close to the minimum (tolmin)
        # But allow the implementation to work and be compatible with a time exceeding maximum (tolmax)

        (tolmin, tolmax) = usb_spec_wall_clock_tolerance(10000, LOW_SPEED)	# USB host-to-device reset is 10ms
        dut._log.info("ELAPSED = {:7f} x {} = {}us  (USB reset spec is 10000us  min={} max={})".format(elapsed, sim_timerLong_factor, elapsed_after_factor, tolmin, tolmax))

        debug(dut, '970_USB_RESET_CHECK')

        # REG_INTERRUPT also has 0x0001000 set for RESET
        assert await wait_for_signal_interrupts(dut, 0) >= 0, f"interrupts = {signal_interrupts(dut)} unexpected state"
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_RESET != 0, f"REG_INTERRUPT expected to see: RESET bit set"
        await ttwb.wb_write(REG_INTERRUPT, INTR_RESET, regwr)	# W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_RESET == 0, f"REG_INTERRUPT expected to see: RESET bit clear"

        # REG_INTERRUPT does not have 0x0010000 set for DISCONNECT this time (unlike first reset)

        assert data == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{data:08x}"

        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        if not GL_TEST:        ## Check FSM(main) state goes to ACTIVE_INIT
            assert fsm_state_expected(dut, 'main', 'ACTIVE_INIT')

        ## FIXME on matter is to confirm we are back listening to the default address and the address filter is reset
        ##       this test assumes we changed address before the reset and tested the address filter
        data = await ttwb.wb_read(REG_FRAME, regrd)
        assert data & 0x00000800 == 0, f"REG_FRAME expects zero frameValid {data:08x}"
        assert data & 0x07ff0000 == 0, f"REG_FRAME expects zero keepaliveCount {data:08x}"

        debug(dut, '970_USB_RESET_END')
        await usb.set_idle()
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)

    ####
    #### 980 DISCONNECT detection and interrupt generation
    ####

    if run_this_test(True):
        debug(dut, '980_USB_DISCONNECT')

        if not GL_TEST:		# fsm_state's are not visible
            assert fsm_state_expected(dut, 'main', 'ACTIVE')

        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"
        dut._log.info("POWER_BITID POWER_BITID={} {} uio_in={}".format(POWER_BITID, 1 << POWER_BITID, str(dut.uio_in.value)))

        signal_power_change(dut, False)		# POWER uio_in bit3

        count = None
        if not GL_TEST:		# fsm_state's are not visible
            count = 0
            while fsm_state(dut, 'main') != 'ATTACHED':
                await ClockCycles(dut.clk, 1)
                count += 1
                dut._log.info("DISCONNECT count={} main={}".format(count, fsm_state(dut, 'main')))
                if count > 100:
                    break
            if count == 0:
                await ClockCycles(dut.clk, 1)	# This is to ensure the signal_power_change() signal stick before next WB access
            dut._log.info("DISCONNECT count={} main={}".format(count, fsm_state(dut, 'main')))

        debug(dut, '981_USB_DISCONNECT_CHECK')

        if not GL_TEST:		# fsm_state's are not visible
            ## Check FSM(main) state goes back to ATTACHED
            assert fsm_state_expected(dut, 'main', 'ATTACHED')
            assert count <= 4, f"main={fsm_state(dut, 'main')} took more than 4 cycles to occur"

        bf = await wait_for_signal_interrupts(dut, not_after=TICKS_PER_BIT)
        assert bf != 0, f"wait_for_interrupt did not occur within {TICKS_PER_BIT} cycles"

        data = await ttwb.wb_read(REG_INTERRUPT, regrd)

        # This is due to 'pullup/power' falling edge
        # REG_INTERRUPT also has 0x0010000 set for DISCONNECT
        assert data & INTR_DISCONNECT != 0, f"REG_INTERRUPT expected to see: DISCONNECT bit set"
        await ttwb.wb_write(REG_INTERRUPT, INTR_DISCONNECT, regwr)	# W1C
        data = await ttwb.wb_read(REG_INTERRUPT, regrd)
        assert data & INTR_DISCONNECT == 0, f"REG_INTERRUPT expected to see: DISCONNECT bit clear"

        assert data == 0, f"REG_INTERRUPT expected to see: all bits clear 0x{data:08x}"

        assert signal_interrupts(dut) == False, f"interrupts = {signal_interrupts(dut)} unexpected state"

        await ClockCycles(dut.clk, TICKS_PER_BIT*16)


        debug(dut, '982_USB_DISCONNECT_END')
        await ClockCycles(dut.clk, TICKS_PER_BIT*32)


    debug(dut, '999_DONE')


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


    await ClockCycles(dut.clk, TICKS_PER_BIT*32)

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

