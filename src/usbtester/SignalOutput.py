#
#
#
#
#
#
#
import cocotb
#import cocotb.task #import Task
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue
from cocotb.utils import get_sim_time

from .cocotbutil import *


# This class is a Signal (output) monitor.
#
class SignalOutput():
    dut = None

    task = None
    running = None
    assert_resolvable = None
    assert_encoded = None

    label = None
    signal_dp = None
    signal_path_dp = None
    signal_dm = None
    signal_path_dm = None

    file_handle = None

    X = 'x'
    SE1 = '1'
    SE0 = '0'
    DP = '+'
    DM = '-'

    def __init__(self, dut):
        assert dut is not None
        self.dut = dut
        self.running = False
        return None

    def unregister(self):
        if self.task is not None:
            self.running = False
            self.task.kill()

        self.file_close()

        self.label = None
        self.signal_dp = None
        self.signal_path_dp = None
        self.signal_dm = None
        self.signal_path_dm = None

    @cocotb.coroutine
    def monitor_coroutine(self, dut):
        dut._log.info("SignalOutput[{}]: started".format(self.label))

        last_encoded = self.encode_signal(self.signal_dp, self.signal_dm)

        same_count = 0
        i = 0
        while self.running:
            yield ClockCycles(dut.clk, 1)

            # What is this all about ?
            #
            # We are trying to be able to isolate sections of output between known markers
            #
            # wait_for_transition is waiting to start
            # wait_since_transition
            #

            if self.assert_resolvable is not None:
                if self.assert_resolvable == True:
                    assert     self.signal_dp.value.is_resolvable and     self.signal_dm.value.is_resolvable, f"assert_resolvable={self.assert_resolvable} dp={str(self.signal_dp.value)} dm={str(self.signal_dm.value)} expecting resolvable"
                if self.assert_resolvable == False:
                    assert not self.signal_dp.value.is_resolvable and not self.signal_dm.value.is_resolvable, f"assert_resolvable={self.assert_resolvable} dp={str(self.signal_dp.value)} dm={str(self.signal_dm.value)} expecting not resolvable"

            encoded = self.encode_signal(self.signal_dp, self.signal_dm)

            if self.assert_encoded is not None:
                assert self.assert_encoded == encoded, f"assert_encoded={self.assert_encoded} dp={str(self.signal_dp.value)} dm={str(self.signal_dm.value)} got {encoded}"

            is_transition = last_encoded != encoded

            if is_transition:
                same_count = 0
            else:
                same_count += 1

            if self.wait_for_transition and is_transition:
                if self.action_close:
                    self.file_close()
                if self.action_open:
                    self.file_open()
                    ## emit premable

            self.file_emit(encoded)


            if self.wait_since_transition and not is_transition and self.wait_since_count >= same_count:
                if self.action_close:
                    self.file_close()
                if self.action_open:
                    self.file_open()

            if is_transition:
                dut._log.info("SignalOutput[{}]: i = {}  {} {} => {}".format(self.label, i, str(self.signal_dp.value), str(self.signal_dm.value), encoded))

            last_encoded = encoded
            i += 1

        retval = i
        dut._log.info("SignalOutput[{}]: finished = {}".format(self.label, retval))
        return retval

    def register(self, label: str, signal_path_dp: str, signal_path_dm: str) -> cocotb.Task:
        self.unregister()

        signal_dp = design_element(self.dut, signal_path_dp)
        if signal_dp is None:
            raise Exception(f"signal {signal_path_dp} does not exist")

        signal_dm = design_element(self.dut, signal_path_dm)
        if signal_dm is None:
            raise Exception(f"signal {signal_path_dm} does not exist")

        self.label = label

        self.signal_path_dp = signal_path_dp
        self.signal_dp = signal_dp

        self.signal_path_dm = signal_path_dm
        self.signal_dm = signal_dm

        self.wait_for_transition = False
        self.wait_since_transition = False
        self.wait_since_count = 0

        self.running = True
        self.task = cocotb.create_task(self.monitor_coroutine(self.dut))

        return self.task

    def assert_resolvable_mode(self, mode: bool = None) -> bool:
        assert mode is None or type(mode) is bool
        retval = self.assert_resolvable
        self.assert_resolvable = mode
        return retval

    # encoded as in the encoded state of the lines
    def assert_encoded_mode(self, mode: str = None) -> str:
        assert mode is None or type(mode) is str
        retval = self.assert_encoded
        self.assert_encoded = mode
        return retval

    # FIXME WIP negative index ?
    def mark_at_transition(self, count: int):
        self.wait_for_transition = True
        self.wait_since_count = count
        return None

    # FIXME WIP
    def mark_now(self, filename: str = None):
        self.wait_for_transition = False
        self.wait_since_transition = False
        self.wait_since_count = 0
        return None

    def encode_signal(self, dp, dm) -> str:
        if dp.value.is_resolvable and dm.value.is_resolvable:
            return self.encode(dp.value, dm.value)
        else:
            return self.X

    def encode(self, dp: bool, dm: bool) -> str:
        if dp:
            if dm:
                return self.SE1
            else:
                return self.DP	# !dm
        else:
            if dm:
                return self.DM	# !dp
            else:
                return self.SE0

    def mark_open_at_transition(self, filename: str, count: int):
        return None

    def mark_open_same_state(self, count: int):
        return None

    def mark_close_at_transition(self, count: int):
        return None

    def mark_close_same_state(self, count: int):
        return None

    def file_close(self) -> bool:
        if self.file_handle is not None:
            self.file_handle.close()
            self.file_handle = None
            return True
        return False

    ## FIXME WIP
    def file_open(self, filename: str = None):
        self.file_close()

        return None

    def file_emit(self, encoded) -> bool:
        if self.file_handle is None:
            return False
        return True


__all__ = [
    "SignalOutput"
]
