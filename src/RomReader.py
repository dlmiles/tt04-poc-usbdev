#
#

class RomReader():
    index = -1
    max_index = -1
    data = None

    def __init__(self, filename):
        fh = open(filename, "r")
        if fh is None:
            error()
        data = self.load_all(filename, fh)
        fh.close()
        
        if data is None:
            self.index = -1
            self.max_index = -1
            self.data = None
        else:
            self.max_index = len(data)
            self.index = 0
            self.data = data
        
        return None
        
    def max_index(self):
        return self.max_index
    
    def has_more(self):
        return self.index < self.max_index

    def next(self):
        if self.index < self.max_index:
            next_value = self.data[self.index]
            self.index += 1
            return next_value
        return None

    def rewind(self):
        self.index = 0
        return 0

    def parse_hex(self, s):
        if type(s) is int:	## FIXME maybe only if in range ?
            return s
        if type(s) is not str:
            return None
        if len(s) == 0:
            return None
        if not s.startswith("0x") and not s.startswith("0X"):
            s = "0x" + s
        #print("PHEX:{}:t={}:l={}".format(s, type(s), len(s)))
        try:
            v = int(s, 16)
            if type(v) is int and v >= 0x00 and v <= 0xff:
                #print("HEX:s={}:v={}:t={}".format(s, v, type(v)))
                return v
        except Exception as err:
            #print("EHEX:{}: Unexpected {}, {}".format(s, err, type(err)))
            pass
        return None

    def load_all(self, filename, fh):
        data = []
        line_number = 0
        pattern = re.compile(r"\s+")
        while True:
            line = fh.readline()
            if line is None or len(line) == 0:
                break
            line = line.rstrip()
            line_number += 1
            # Skip comment lines and blank lines
            if re.match(r'^\s*#', line) or re.fullmatch(r'^\s*$', line):
                #print("SKIP:{}:{}:{}".format(filename, line_number, line))
                continue
            words = pattern.split(line)
            #print("WORDS:{}:{}:l={}:t={}".format(filename, line_number, len(words), type(words)))
            for word in words:
                in8 = self.parse_hex(word)
                if in8 is None:
                    print("WARN:{}:{} invalid data: \"{}\"".format(filename, line_number, word))
                    continue
                data.append(in8)
    
        print("LOADED:{}:{} with {} bytes".format(filename, line_number, len(data)))
        return data
