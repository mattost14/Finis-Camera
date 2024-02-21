from raw_data import process_raw_data

class ingest(object):
  
  def __init__():
    super().__init__()

  # def _complete_frame(self, data_point, camera, data):
  #   if frame_start[camera] is not None:
  #       data_point['Time'] = frame_start[camera]
  #   data_point[camera] = data
  #   # if we're not collecting data then we're all done here
  #   if not self._collecting(camera): return
  #   # decrement counter for current camera
  #   print(self._collect_frames[camera])
  #   if self._collect_frames[camera] is not None:
  #       # wait to start counting frames until we see a sync trigger
  #       #if not self._collect_started[camera]: return
  #       self._collect_frames[camera] -= 1

  #       # keep waiting if not all cameras have collected the requested number of frames
  #       #for camera in CAMERAS:
  #       #    if self._collect_frames[camera] > 0: return
  #       #if any camera collects the requested number of frames then stop
  #       if self._collect_frames[camera] > 0: return
  #   # keep waiting if the timeout has not been hit yet
  #   if self._collect_timeout is not None:
  #       if datetime.utcnow() < self._collect_timeout: return
  #   # stop collection
  #   self._set_collect(None, None)
  #   self.collect_done.emit()
  #   if self._stream is None: return
  #   self._stop_collection()

  def _process_message(self, data):
    global sysclk_epoch
    data_point = {}
    msg_type = int.from_bytes(data[0:4], byteorder='little')
    data = data[4:-4] # remove the message type and CRC before working with the data further
    # currently only interested in raw camera data
    if msg_type == 3:#message_type.data_rows:
        (complete, camera, data) = process_raw_data(data)
        data_point[camera] = data
        # if complete:
        #     self._complete_frame(data_point, camera, data)
    # elif msg_type == 132:#message_type.camera_sync_info:
        # camera_idx = int.from_bytes(data[0:0+2], byteorder='little')
        # sysclk_at_pps = int.from_bytes(data[2:2+8], byteorder='little') / sysclk_hz
        # timestamp = sysclk_epoch + timedelta(seconds=sysclk_at_pps) if sysclk_epoch is not None else None
        # camera = camera_names[1+camera_idx]
        # frame_start[camera] = timestamp.timestamp() if timestamp is not None else None
        # if self._collecting(camera):
        #     self._collect_started[camera] = True
    # elif msg_type == 131:#message_type.pps_sync_info:
        # sysclk_at_pps = int.from_bytes(data[0:0+8], byteorder='little') / sysclk_hz
        # sysclk_tat = int.from_bytes(data[8:8+8], byteorder='little') / sysclk_hz
        # tai = int.from_bytes(data[16:16+4], byteorder='little')
        # timestamp = tai_epoch + timedelta(seconds=tai)
        # if sysclk_epoch is None:
        #     sysclk_epoch = timestamp - timedelta(seconds=sysclk_tat)
        #     sysclk_epoch -= timedelta(microseconds=sysclk_epoch.microsecond)
        # timestamp = sysclk_epoch + timedelta(seconds=sysclk_at_pps)
        # data_point['Time'] = timestamp.timestamp()
        # data_point['Trigger'] = ['PPS']
    # elif msg_type == 4:#message_type.ps_housekeeping:
        # tai_seconds = int.from_bytes(data[8:8+8], byteorder='little') / housekeeping_hz
        # timestamp = tai_epoch + timedelta(seconds=tai_seconds)
        # queue_length = int.from_bytes(data[16:16+4], byteorder='little')
        # if self._t0_offset is None:
        #     self._t0_offset = queue_length
        # queue_length /= 1024*1024
        # self._print_queue(queue_length)
        # self._stream.queue_okay = (queue_length < 20.0)
        # data_point['Queue_Length'] = [queue_length]
        # data_point['Time'] = timestamp.timestamp()
    return data_point