#
#
#
#
#
#
#
from typing import Any

import cocotb
#import cocotb.task #import Task
from cocotb.triggers import ClockCycles
from cocotb.binary import BinaryValue
from cocotb.utils import get_sim_time

from .cocotbutil import *
from .SignalAccessor import *


# This class is a Signal (output) monitor.
#
class SignalOutput():
    X = 'x'
    SE1 = '1'
    SE0 = '0'
    DP = '+'
    DM = '-'

    def __init__(self, dut):
        assert dut is not None
        self._dut = dut
        self._running = False
        self._task = None

        self._assert_resolvable = None
        self._assert_encoded = None

        self._file_handle = None

        self.unregister()	# initialize members

        return None

    def unregister(self):
        if self._task is not None:
            self._running = False
            self._task.kill()

        self.file_close()

        self._label = None
        self._signal_dp = None
        self._signal_path_dp = None
        self._signal_dm = None
        self._signal_path_dm = None

    @cocotb.coroutine
    def monitor_coroutine(self, dut):
        dut._log.info("SignalOutput[{}]: started".format(self._label))

        last_encoded = self.encode_signal(self._signal_dp, self._signal_dm)

        same_count = 0
        i = 0
        while self._running:
            yield ClockCycles(dut.clk, 1)

            # What is this all about ?
            #
            # We are trying to be able to isolate sections of output between known markers
            #
            # wait_for_transition is waiting to start
            # wait_since_transition
            #

            if self._assert_resolvable is not None:
                if self._assert_resolvable == True:
                    assert     self._signal_dp.value.is_resolvable and     self._signal_dm.value.is_resolvable, f"assert_resolvable={self._assert_resolvable} dp={str(self._signal_dp.value)} dm={str(self._signal_dm.value)} expecting resolvable"
                if self._assert_resolvable == False:
                    assert not self._signal_dp.value.is_resolvable and not self._signal_dm.value.is_resolvable, f"assert_resolvable={self._assert_resolvable} dp={str(self._signal_dp.value)} dm={str(self._signal_dm.value)} expecting not resolvable"

            encoded = self.encode_signal(self._signal_dp, self._signal_dm)

            if self._assert_encoded is not None:
                assert self._assert_encoded == encoded, f"assert_encoded={self._assert_encoded} dp={str(self._signal_dp.value)} dm={str(self._signal_dm.value)} got {encoded}"

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
                dut._log.info("SignalOutput[{}]: i = {}  {} {} => {}".format(self._label, i, str(self._signal_dp.value), str(self._signal_dm.value), encoded))

            last_encoded = encoded
            i += 1

        retval = i
        dut._log.info("SignalOutput[{}]: finished = {}".format(self._label, retval))
        return retval

    # dp_sa_or_path: SignalAccessor|str
    # dm_sa_or_path: SignalAccessor|str
    def register(self, label: str, dp_sa_or_path: Any, dm_sa_or_path: Any) -> cocotb.Task:
        self.unregister()

        (signal_dp, signal_path_dp) = SignalAccessor.build(self._dut, dp_sa_or_path)

        #signal_dp = design_element(self._dut, signal_path_dp)
        #if signal_dp is None:
        #    raise Exception(f"signal {signal_path_dp} does not exist")

        (signal_dm, signal_path_dm) = SignalAccessor.build(self._dut, dm_sa_or_path)

        #signal_dm = design_element(self._dut, signal_path_dm)
        #if signal_dm is None:
        #    raise Exception(f"signal {signal_path_dm} does not exist")

        self._label = label

        self._signal_path_dp = signal_path_dp
        self._signal_dp = signal_dp

        self._signal_path_dm = signal_path_dm
        self._signal_dm = signal_dm

        self.wait_for_transition = False
        self.wait_since_transition = False
        self.wait_since_count = 0

        self._running = True
        self._task = cocotb.create_task(self.monitor_coroutine(self._dut))

        return self._task

    def assert_resolvable_mode(self, mode: bool = None) -> bool:
        assert mode is None or type(mode) is bool
        retval = self._assert_resolvable
        self._dut._log.info("SignalOutput.assert_resolvable_mode({}) = {} (old)".format(mode, retval))
        self._assert_resolvable = mode
        return retval

    # encoded as in the encoded state of the lines
    def assert_encoded_mode(self, mode: str = None) -> str:
        assert mode is None or type(mode) is str
        retval = self._assert_encoded
        self._dut._log.info("SignalOutput.assert_encoded_mode({}) = {} (old)".format(mode, retval))
        self._assert_encoded = mode
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
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None
            return True
        return False

    ## FIXME WIP
    def file_open(self, filename: str = None):
        self.file_close()

        return None

    def file_emit(self, encoded) -> bool:
        if self._file_handle is None:
            return False
        return True


__all__ = [
    "SignalOutput"
]
