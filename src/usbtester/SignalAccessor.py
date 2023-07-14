#
#
#
#
#
#
import cocotb
from cocotb.binary import BinaryValue

from .cocotbutil import *


# Provides a way to encapsulte and isolate a signal
# Like a wide-bus to a narrow-bus or bit
class SignalAccessor():
    def __init__(self, dut, path: str, bitid: int = None, width: int = 1) -> None:
        assert dut is not None
        assert isinstance(path, str)
        assert bitid is None or bitid >= 0, f"bitid is invalid: {bitid}"
        assert width > 0, f"width is out of range > 0: {width}"
        assert width == 1, f"width != 1 is not supported"	# TODO

        self._dut = dut
        self._path = path
        self._bitid = bitid
        self._width = width

        signal = design_element(dut, path)
        if signal is None:
            raise Exception(f"Unable to find signal path: {path}")
        self._signal = signal

        # FIXME maybe for efficient can be optimize the 3 scenarios and generate a value(self)
        #   function and attach
        # 0: direct signal.value (no change)
        # 1: single bit isolation
        # 2: width>1 bus isolation

        return None


    @property
    def value(self):
        if self._bitid is not None:
            vstr = str(self._signal.value)
            ## isolate
            if self._width == 1:
                bstr = vstr[-self._bitid-1]		# minus prefix due to bit0 on right hand side
            else:
                assert False, f"width = {width}"
            #print(f"SignalAccessor(path={self._path}) = {vstr} => {self._bitid} for {bstr}")
            v = BinaryValue(bstr, n_bits=len(bstr))
            return v

        return self._signal.value


    @property
    def raw(self):
        return self._signal


    @property
    def path(self) -> str:
        return self._path


    # sa_or_path: SignalAccessor|str
    @staticmethod
    def build(dut, sa_or_path) -> tuple:	# SignalAccessor, str
        if isinstance(sa_or_path, str):
            sa = SignalAccessor(dut, sa_or_path)
        if isinstance(sa_or_path, SignalAccessor):
            sa = sa_or_path
        assert sa is not None

        return (sa, sa.path)


__all__ = [
    'SignalAccessor'
]
