import numpy as np

from ccsdspy import (FixedLength, PacketField)
from enum import (IntEnum, auto)

class loki_cameras(IntEnum):
    unknown = 0
    visible = auto()
    swir = auto()
    mwir = auto()
    lwir = auto()
    visible_hd = auto()
    MAX = 0x1fff

camera_names = {
    loki_cameras.visible: 'Visible',
    loki_cameras.swir: 'SWIR',
    loki_cameras.mwir: 'MWIR',
    loki_cameras.lwir: 'LWIR',
    loki_cameras.visible_hd: 'Visible',
}

CAMERAS = [ 'Visible', 'SWIR', 'MWIR', 'LWIR' ]


RAW_ROWS = 8

class frame_buffer(object):
    complete = False
    _buffer = None
    _height = 0
    _width = 0
    
    def __init__(self, width, height):
        super().__init__()
        self._buffer = bytearray(width * height * 2)
        self._height = height
        self._width = width
    
    @property
    def data(self):
        data = np.frombuffer(self._buffer, dtype=np.uint16)
        data.shape = (self._height, self._width)
        return data
    
    def save(self, filename):
        data = np.frombuffer(self._buffer, dtype=np.uint16)
        data.shape = (self._height, self._width)
        img = Image.fromarray(data)
        img.save(filename)
    
    def clear(self):
        self._buffer = bytearray(self._width * self._height * 2)
    
    def append(self, row_number, data):
        start = self._width*2*row_number
        size = self._width*2*RAW_ROWS
        if size != len(data):
            raise Exception('raw frame data does not match expected size/number of rows')
        if start+size > len(self._buffer):
            raise Exception('tried to store data past end of image')
        self._buffer[start:start+size] = data[0:size]
        self.complete = (start+size == len(self._buffer))

frames = {
    loki_cameras.visible:    {'started': False, 'start': 0, 'frame_buffer': frame_buffer(972, 736)},
    loki_cameras.swir:       {'started': False, 'start': 0, 'frame_buffer': frame_buffer(640, 512)},
    loki_cameras.mwir:       {'started': False, 'start': 0, 'frame_buffer': frame_buffer(640, 512)},
    loki_cameras.lwir:       {'started': False, 'start': 0, 'frame_buffer': frame_buffer(640, 512)},
    loki_cameras.visible_hd: {'started': False, 'start': 9, 'frame_buffer': frame_buffer(1944, 1465)},
}

pkt_format = FixedLength([
     PacketField(name='timestamp',  data_type='uint', bit_length=64, byte_order='little'),
     PacketField(name='camera_idx', data_type='uint', bit_length=16, byte_order='little'),
     PacketField(name='row_number', data_type='uint', bit_length=16, byte_order='little'),
], length=12)

def load_fields(data, fast=False):
    if not fast:
        fields = pkt_format.load(data)
        for field in fields:
            fields[field] = int(fields[field])
        return fields
    fields = {}
    fields['timestamp'] = int.from_bytes(data[0:8], byteorder='little')
    fields['camera_idx'] = int.from_bytes(data[8:10], byteorder='little')
    fields['row_number'] = int.from_bytes(data[10:12], byteorder='little')
    return fields

def is_started(camera_idx, row_number):
    if row_number == frames[camera_idx]['start']:
        frames[camera_idx]['frame_buffer'].clear()
        frames[camera_idx]['started'] = True
    return frames[camera_idx]['started']

def process_raw_data(data):
    fields = load_fields(data, True)
    timestamp = fields['timestamp']
    camera_idx = fields['camera_idx']
    row_number = fields['row_number']
    if is_started(camera_idx, row_number):
        frame_buffer = frames[camera_idx]['frame_buffer']
        try:
            frame_buffer.append(row_number, data[14:])
        except:
            print('ERROR', timestamp, camera_idx, row_number)
        complete = frame_buffer.complete
        data = frame_buffer.data
    else:
        complete = False
        data = None
    return (complete, camera_names[camera_idx], data)
