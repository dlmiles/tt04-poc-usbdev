#
#
#
#
#

# Need to make a class just to make things easier with managing payloads
# Only handles byte granularity
class Payload():
    def __init__(self, data):
        # FIXME perform data conversions
        assert type(data) is bytearray, f"data is type {type(data)} and not {type(bytearray())}"
        self._data = data

    def __len__(self):
        #print("Payload.len() = {}".format(len(self._data)))
        return len(self._data)

    class iterator():
        def __init__(self, data):
            assert type(data) is bytearray, f"data is type {type(data)} and not {type(bytearray())}"
            self._data = bytearray(data)	# copy
            self._index = 0

        def has_more(self) -> bool:
            return self._index < len(self._data)

        def __next__(self):
            if self.has_more():
                v = self._data[self._index]
                #print("Payload.next() = {}/{} value={:02x}".format(self._index, len(self._data), v))
                self._index += 1
                return v
            #print("Payload.next() = {}/{} STOP".format(self._index, len(self._data)))
            raise StopIteration()

        def next_or_default(self, default_value = None) -> int:
            if self.has_more():
                return self.__next__()
            return default_value

    def __iter__(self):
        #print("Payload.iter() = {}".format(len(self._data)))
        return Payload.iterator(self._data)

    def __getitem__(self, index: int) -> int:
        if isinstance(index, int):
            assert index >= 0, f"Payload.getitem32(index): index {index} out of range"
            if index > len(self._data):
                raise IndexError(f"Payload.__getitem__(index): index {index} out of range, len={len(self._data)}")
            else:
                return self._data[index]
        raise TypeError(f"Invalid Argument Type: {type(index)} try {type(int)}")

    def getitem32(self, index: int) -> int:
        if isinstance(index, int):
            assert index >= 0, f"Payload.getitem32(index): index {index} out of range"
            byteindex = index * 4
            if byteindex+4 > len(self._data):
                raise IndexError(f"Payload.getitem32(index): index {index} out of range, bytelen={len(self._data)}")
            else:
                val = self._data[byteindex]
                val |= self._data[byteindex+1] << 8
                val |= self._data[byteindex+2] << 16
                val |= self._data[byteindex+3] << 24
                return val
        raise TypeError(f"Invalid Argument Type: {type(index)} try {type(int)}")

    def append(self, other: 'Payload') -> int:
        assert type(other) is Payload, f"type(other) is {type(other)} and not {type(Payload)}"
        self._data.extend(other.data)
        return self.__len__()

    def bit_stuff_count(self) -> int:
        accum = 0
        last = None
        count = 0.0
        #xcount = 0.0
        for b in self._data:
            for bid in range(8):
                bmask = 1 << bid
                bit = (b & bmask) != 0
                #print("bit_stuff_count() len={} count={} b={:x} bmask={:x} bit={} last={} accum={}".format(len(self), count, b, bmask, bit, last, accum))
                if last is None:
                    last = bit
                elif bit == last:
                    accum += 1
                    if accum >= 6:
                        count += 1.0
                        accum = 0
                else:
                    accum = 0
            # This worked well for a while, the accuracy for the testdata used was pretty close
            #if b == 0xff:	# FIXME crude!
            #    xcount += 1.25
            #else:
            #    xcount += 0.10	# guess factor
        #if xcount > 1.0:
        #    xcount += 1.0	# round up
        #print("bit_stuff_count() len={} count={} xcount={}".format(len(self), count, xcount))
        return int(count)

    def equals(self, other: 'Payload') -> bool:
        assert type(self) is type(other)
        assert type(self) == type(other)
        assert self.__len__() == other.__len__(), f"Payload.equals() length mismatch {self.__len__()} != {other.__len__()}"
        i = 0
        for b in other:
            if b != self._data[i]:
                print("Payload.equals() MISMATCH at {} with values (ours) {:02x} != {:02x} (other)".format(i, self._data[i], b))
                return False
            i += 1
        return True

    @staticmethod
    def int32(*values) -> 'Payload':
        # convert to bytes
        bytes = bytearray()
        for v in values:
            bytes.append((v      ) & 0xff)
            bytes.append((v >>  8) & 0xff)
            bytes.append((v >> 16) & 0xff)
            bytes.append((v >> 24) & 0xff)
        #print("int32() = {}".format(bytes))
        return Payload(bytes)

    @staticmethod
    def empty() -> 'Payload':
        return Payload(bytearray())

    @staticmethod
    def fill(byte: int, count: int = 0) -> 'Payload':
        ba = bytearray()
        while count > 0:
            ba.extend([byte & 0xff])
            count -= 1
        return Payload(ba)

    @staticmethod
    def random(byte: int, count: int = 0) -> 'Payload':
        ba = bytearray()
        while count > 0:
            ba.extend([random.randint(0x00, 0xff)])
            count -= 1
        return Payload(ba)



__all__ = [
    'Payload'
]
