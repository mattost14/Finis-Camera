"""Internal decoding routines."""

from enum import IntEnum

import sys

__author__ = 'Erich E. Hoover <erich.e.hoover@gmail.com>'

_CCSDS_HEADER_SIZE = 6
_TCP_MAX_PACKET_SIZE = 65535
_CCSDS_MAX_PACKET_SIZE = 2048 + _CCSDS_HEADER_SIZE

class _CCSDS_SEQUENCE(IntEnum):
    CONTINUATION = 0
    FIRST_SEGMENT = 1
    LAST_SEGMENT = 2
    UNSEGMENTED = 3

class _header(object):
    _header = bytearray(_CCSDS_HEADER_SIZE)
    _loaded = False
    _format = None
    _data = None
    
    def __init__(self):
        super().__init__()
        
        from .interface import (FixedLength, PacketField)
        self._format = FixedLength([
             PacketField(name='PVN',              data_type='uint', bit_length=3),
             PacketField(name='Type',             data_type='uint', bit_length=1),
             PacketField(name='SecondaryHeader',  data_type='uint', bit_length=1),
             PacketField(name='APID',             data_type='uint', bit_length=11),
             PacketField(name='SequenceFlags',    data_type='uint', bit_length=2),
             PacketField(name='SequenceCount',    data_type='uint', bit_length=14),
             PacketField(name='PacketDataLength', data_type='uint', bit_length=16),
        ], length=6)
    
    def load(self, data):
        self._header[:] = data[0:_CCSDS_HEADER_SIZE]
        self._loaded = False
    
    def _load(self):
        if self._loaded: return
        self._data = self._format.load(self._header)
    
    @property
    def PVN(self):
        self._load()
        return int(self._data['PVN'])
    
    @property
    def type(self):
        self._load()
        return int(self._data['Type'])
    
    @property
    def secondary_header(self):
        if self._loaded:
            return int(self._data['SecondaryHeader'])
        return (self._header[0] >> 3) & 0x1
    
    @property
    def APID(self):
        self._load()
        return int(self._data['APID'])
    
    @property
    def sequence_flags(self):
        if self._loaded:
            return int(self._data['SequenceFlags'])
        return self._header[2] >> 6
    
    @property
    def sequence_count(self):
        self.load()
        return int(self._data['SequenceCount'])
    
    @property
    def packet_data_length(self):
        if self._loaded:
            return int(self._data['PacketDataLength'])
        return (self._header[4] << 8) + self._header[5]

class _packet_buffer(object):
    _buffer = bytearray(_CCSDS_MAX_PACKET_SIZE)
    complete = True
    header = None
    
    def __init__(self):
        super().__init__()
        self.header = _header()
    
    @property
    def size(self):
        size = self._size - _CCSDS_HEADER_SIZE
        size -= _CCSDS_HEADER_SIZE if self.header.secondary_header else 0
        return size
    
    @property
    def buffer(self):
        # TODO: optionally check CRC here
        return self._buffer[0:self.size]
    
    def reset(self):
        self.complete = True
    
    def decode(self, data):
        if self.complete:
            if not (data[0] == 1 or data[0] == 9): return False
            old_pos = 0
            self._dst_offset = 0
            src_offset = _CCSDS_HEADER_SIZE
            self.header.load(data)
            self._size = 1 + src_offset + self.header.packet_data_length
            src_offset += _CCSDS_HEADER_SIZE if self.header.secondary_header else 0
        else:
            src_offset = 0
            old_pos = self._pos
        self._pos = min(old_pos + len(data), self._size)
        size = self._pos - old_pos
        self.complete = (self._size == self._pos)
        self._buffer[self._dst_offset:self._dst_offset+size] = data[src_offset:size]
        self._dst_offset += size - src_offset
        self.remainder = self._size - self._pos
        if (self.remainder == 0) and (size < len(data)):
            self.remainder = size - len(data)
        return True

class _message_handler(object):
    buffer = bytearray()
    read_failed = False
    _remainder = 0
    header = None
    _offset = 0
    data = b""
    size = 0
    
    def __init__(self, stream):
        super().__init__()
        if hasattr(stream, 'recv'):
            self._read = stream.recv
        else:
            self._read = stream.read
        self._pkt = _packet_buffer()
        self.read_failed = False
    
    def _advance(self):
        self._offset += len(self.data)
        # manage partially processed packets
        if self._remainder < 0:
            self._offset += self._remainder
            self.data = self.data[self._remainder:]
        elif self._remainder > 0:
            self.data = self._read(self._remainder)
        else:
            self.data = b""
    
    def _read_more(self):
        # read in more data if we don't have enough bytes for the header
        # (including the possibility of a secondary header)
        while len(self.data) < 2*_CCSDS_HEADER_SIZE:
            self.data += self._read(_TCP_MAX_PACKET_SIZE)
    
    def _decode(self):
        # decode CCSDS packet buffer
        if not self._pkt.decode(self.data):
            # this case is primarily for a failed initial read
            self._pkt.reset()
            self._remainder = 0
            self.read_failed = True
            print(f'{self._offset}: failed to read', file=sys.stderr)
            return False
        self._remainder = self._pkt.remainder
        #print(f'{self._offset}: success')
        return self._pkt.complete
    
    def decode(self):
        self._advance()
        self._read_more()
        if not self._decode(): return False
        flags = self._pkt.header.sequence_flags
        if (flags == _CCSDS_SEQUENCE.FIRST_SEGMENT) or (flags == _CCSDS_SEQUENCE.UNSEGMENTED):
            self.buffer = self._pkt.buffer # reset buffer
            self.header = self._pkt.header # give caller access to initial header
            self.size = 0
        elif (flags == _CCSDS_SEQUENCE.CONTINUATION) or (flags == _CCSDS_SEQUENCE.LAST_SEGMENT):
            self.buffer += self._pkt.buffer # append to buffer
        self.size += self._pkt.size
        # return True = message complete
        return (flags == _CCSDS_SEQUENCE.LAST_SEGMENT) or (flags == _CCSDS_SEQUENCE.UNSEGMENTED)

