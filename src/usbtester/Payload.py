#
#
#
#
#

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
            self.data = bytearray(data)	# copy
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



__all__ = [
    'Payload'
]