from socket import (socket, AF_INET, SOCK_STREAM, SHUT_RDWR)
from ccsdspy import Message
import time
from raw_data import process_raw_data
import re
import subprocess
import math
from tifffile import (TiffWriter, TiffFile)
import matplotlib.pyplot as plt
from IPython.display import display, clear_output
import numpy as np


### CAMERA CONNECTION INFORMATION ###
cameraAddress = "rroci@129.123.5.125"
cameraCommand = "taucmd -f /dev/ttyUSB0"

def _process_message(data):
    # global sysclk_epoch
    data_point = {}
    msg_type = int.from_bytes(data[0:4], byteorder='little')
    data = data[4:-4] # remove the message type and CRC before working with the data further
    # currently only interested in raw camera data
    if msg_type == 3:#message_type.data_rows:
        (complete, camera, data) = process_raw_data(data)
        if complete:
            data_point[camera] = data
    elif msg_type == 4:#message_type.ps_housekeeping:
        queue_length = int.from_bytes(data[16:16+4], byteorder='little')
        queue_length /= 1024*1024 # bytes -> MB
        data_point['Queue_Length'] = queue_length #units: bytes, It should <100MB
    return data_point

def extract_hex_values_from_response(input_string):
    # Find all occurrences of the phrase "Received response from Tau (len: N)"
    matches = re.finditer(r'Received response from Tau \(len: (\d+)\)', input_string)

    # Find the last match
    last_match = None
    for match in matches:
        last_match = match

    if last_match:
        # Get the length N from the last match
        length_n = int(last_match.group(1))

        # Get the substring after the last match
        substring_after_last_match = input_string[last_match.end():]

        # Extract N hexadecimal values using a regular expression
        # hex_values = re.findall(r'([0-9A-Fa-f]+)', substring_after_last_match)[:length_n]
        hex_values = re.findall(r'\b0x[0-9A-Fa-f]{2}\b', substring_after_last_match)[:length_n]
        return hex_values
    else:
        return []
    

class tauSWIRcamera:
    fpa_size = [512, 640]
    pitch = 15              # um, detector size
    detectorArea_cm2 = (pitch*1e-4)**2  # cm2, detector area
    maxFPS = 60
    digitization = 14
    QE = 0.6
    _validGainModes = {"high":0,"medium":1,"low":2}
    _wellSizes = {"low": 1.35e6, "medium" : 113e3, "high": 38e3}
    CAM1_SerialNumber = 10682
    CAM2_SerialNumber = 10683
    cameraNames = {CAM1_SerialNumber: "CAM1", CAM2_SerialNumber: "CAM2"}

    def __init__(self, hostname, port, syncMode = "DISABLED"):
        # Check if syncMode input is valid
        if syncMode not in ["DISABLED", "MASTER", "SLAVE"]: 
            raise "Invalid sync mode. Options: DISABLED, MASTER, SLAVE"
        # Record connection parameters
        self.hostname = hostname
        self.port = port
        # Run setup script
        self._runSetupScript(syncMode)
        # Identify camera as CAM1 or CAM2 based on the serial number
        self.cameraSerialNumber = self.getSerialNumber()
        self.name = self.cameraNames[self.cameraSerialNumber]

    def _runSetupScript(self, syncMode):
        print("## START CAMERA SETUP ##")


        # 1 - DISABLE ANALOG MODE AND ZOOM 
        print(f"1. Analog mode set to: DISABLED")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"0F","0002","-d 2"], capture_output=True)

        # 2 - SET EXTERNAL SYNC MODE
        print(f"2. External Sync Mode set to: {syncMode}")
        if syncMode == "MASTER":
            cmd = "0002"
        elif syncMode == "SLAVE":
            cmd = "0001"
        else:
            cmd = "0000"
        subprocess.run(["ssh", cameraAddress, cameraCommand,"21",cmd,"-d 2"], capture_output=True)

        # 3 - SET AGC ALGORITHM TO MANUAL
        print("3. AGC set to: MANUAL")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"13","0003","-d 2"], capture_output=True)

        # 3 - SET BRIGHTNESS LEVEL
        print("3. Brightness Level set to: 0")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"15","0000","-d 2"], capture_output=True)

        # 3 - SET CONTRAST LEVEL
        print("3. Contrast Level set to: 0")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"14","0000","-d 2"], capture_output=True)

        # 4 - DISABLE AUTO-EXPOSURE
        print("4. Auto-Exposure set to: DISABLED")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","02120000","-d 2"], capture_output=True)

        # 5 - SET CMOS BIT DEPTH TO 14BITS
        print("5. CMOS bit depth set to: 14-BITS")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"12",f"0600","-d 2"], capture_output=True)

        # 6 - SET CAMERA LINK BIT DEPTH TO 14BITS
        print("6. Camera Link bit depth set to: 14-BITS")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"12","0700","-d 2"], capture_output=True)

        # 7 - SET INTEGRATION MODE UNRESTRICTED
        print("7. Integration mode set to: ITR only (Integrate Then Read)")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","020E012300000001","-d 2"], capture_output=True)
        # print("7. Integration mode set to: UNRESTRICTED")
        # subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","020E012300000000","-d 2"], capture_output=True)

        # 8 - SET FPA SET POINT TEMP TO 20C
        print("8. FPA Set Point Temperature set to: 20oC")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED",f"020F00010001","-d 2"], capture_output=True)

        # 9 - SET THIS SETTINGS AS POWER-ON DEFAULT
        print("9. Settings set as Power-on Default")
        subprocess.run(["ssh", cameraAddress, cameraCommand,"01","-d 2"], capture_output=True)

        print("## CAMERA SETUP COMPLETED ##")

    def _decode_tau_response(self, hex_response, command):
        if command == "get-int-time": # GET INT TIME
            reply_length = 4 # number of bytes
            # hex_values_rsp = hex_response[-reply_length-2:-2]
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            combined_hex_value = "".join(hex_values_rsp)
            # Remove the "0x" prefix if present and convert to decimal
            decimal_value = int(combined_hex_value, 16)
            integration_time_ms = decimal_value / 5704.807
            return integration_time_ms
        elif command == "get-FPA-temp": # READ_SENSOR
            reply_length = 2 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            combined_hex_value = "".join(hex_values_rsp)
            decimal_value = int(combined_hex_value, 16)
            return decimal_value/10
        elif command == "get-TEC-param": # READ_SENSOR
            reply_length = 6 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            TECisON = True if hex_values_rsp[3] == '01' else False
            TEC_entry = hex_values_rsp[5]
            FPA_setPointTemp = {"00": 0, "01": 20, "02": 40, "03": 45}
            print("TEC is ON") if TECisON else print("TEC is OFF")
            print(f"FPA set point temperature (oC): {FPA_setPointTemp[TEC_entry]}")
        elif command == "get-Gain": # COOLED_CORE_ COMMAND
            reply_length = 8 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            gainN = int(hex_values_rsp[-1][-1])
            return list(self._validGainModes.keys())[list(self._validGainModes.values()).index(gainN)]
        elif command == "get-Priority": # COOLED_CORE_ COMMAND
            reply_length = 8 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            X = int(hex_values_rsp[-1][-1])
            if X == 1 : return "Integration"
            elif X == 2: return "Readout"
            else:  return -1
        elif command == "get-FPS": # COOLED_CORE_ COMMAND
            reply_length = 12 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            fps_hex = hex_values_rsp[3]
            fps = int(fps_hex,16)
            return fps
        elif command == "get-serial-number":
            reply_length = 8 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            serialNumber_hex = "".join(hex_values_rsp[2:4])
            serialNumber = int(serialNumber_hex,16)
            return serialNumber
        elif command == "get-CMOS-bit-depth":
            reply_length = 2 # number of bytes
            hex_values_rsp = [hex_value[2:] for hex_value in hex_response[-reply_length-2:-2]]
            resp_hex = int(hex_values_rsp[1],16)          
            if resp_hex == 0 : return 14
            elif resp_hex == 1:  return 8

    
    def setSensorGain(self, gainMode):
        if gainMode not in self._validGainModes: 
            raise "Invalid gain mode. Options: high, medium, low"
        else:
            self.gainMode = gainMode
            subprocess.run(["ssh", cameraAddress, cameraCommand,"ED",f"020E00140000000{self._validGainModes[gainMode]}","-d 2"], capture_output=True)
            if self.getSensorGain() == gainMode : 
                self.wellSize = self._wellSizes[gainMode]
                self.quantizationStepSize = self.wellSize / (2**self.digitization)
                print(f"Gain set to: {gainMode} - Wellsize: {self.wellSize} e-")
            else:
                raise "Error on setting the gain!"
            
    def setIntTime(self, int_time_ms):
        multiplier = 5707.807
        result = int(int_time_ms * multiplier)
        # Convert decimal number to hexadecimal and remove '0x' prefix
        hexadecimal_string = hex(result)[2:]
        # Ensure the hexadecimal string has 8 digits by padding with zeros if necessary
        hexadecimal_string = hexadecimal_string.zfill(8)
        subprocess.run(["ssh", cameraAddress, cameraCommand,"A1",hexadecimal_string,"-d 2"], capture_output=True)
        # Now check if the gain change was accepted
        intTimeFromCamera = self.getIntTime()
        if abs(intTimeFromCamera - int_time_ms)/int_time_ms < 0.02 : # Tolerate 1% difference
            print(f"Int. Time set to: {intTimeFromCamera:.2f}ms")
            self.intTime_ms = intTimeFromCamera
        else:
            raise "Error on setting the integration time!"

    def setPriority(self, priority):
        X = {"Integration":1, "Readout":2}
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED",f"020E011A0000000{X[priority]}","-d 2"], capture_output=True)
        # Now check if the change was accepted
        actualPriority = self.getPriority()
        if actualPriority ==  priority: 
            print(f"Priority set to: {priority}")
        else:
            raise "Error on setting the priority!"

    def setFPS(self, fps):
        # Convert to hexadecimal with leading '0x' prefix
        fps_hex = hex(fps)
        # Extract the hexadecimal part without the '0x' prefix
        fps_hex = fps_hex[2:]
        # Ensure the hexadecimal string is two digits by padding with leading zeros if necessary
        fps_hex = fps_hex.zfill(2)
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED",f"021000{fps_hex}0001000102000280","-d 2"], capture_output=True)
        # Now check if the gain change was accepted
        time.sleep(1)
        actualFPS = self.getFPS()
        if actualFPS ==  fps: 
            print(f"Frame rate set to: {fps}")
        else:
            raise "Error on setting the frame rate!"
        
    def setCMOSBitDepth(self, bits):
        # Options
        options = {14: 0, 8: 1}
        subprocess.run(["ssh", cameraAddress, cameraCommand,"12",f"060{options[bits]}","-d 2"], capture_output=True)
        # Now check if the gain change was accepted
        time.sleep(2/30)
        actualCMOSBitsDepth = self.getCMOSBitDepth()
        if actualCMOSBitsDepth ==  bits: 
            print(f"CMOS bit depth set to: {bits}")
        else:
            raise "Error on setting the CMOS bit depth!"
        
    def setFPATempSetPoint(self,n, plot=False):
        # The temperature setpoint is set based on the information provided in the "Table 3-4, TEC Control Table Showing Default Values", page 17 of the Tau-Swir-Product-specificaiton
        FPA_temp_setpoint_options = [0, 20, 40, 45] #oC
        FPA_temp_tolerance_max = [2,22,42, 75] #oC
        FPA_temp_tolerance_min = [-40,18,38,43] #oC
        FPA_temp_setpoint = FPA_temp_setpoint_options[n]
        print("Previous TEC parameters:")
        self.getTECparam()
        subprocess.run(["ssh", cameraAddress, cameraCommand,"ED",f"020F0001000{n}","-d 2"], capture_output=True)
        time.sleep(2/30)
        # Now check if the set point was accepted
        print("New TEC parameters:")
        self.getTECparam()
        # Wait until temperature is close to set point
        temp_actual = self.getFPAtemp()
        # condition = temp_actual<=FPA_temp_tolerance_max[n] and temp_actual>=FPA_temp_tolerance_min[n] 
        condition = abs(self.getFPAtemp() - FPA_temp_setpoint) < .2
        t0 = time.time()
        timeOut = False
        temp_values = []
        time_values = []

        while(condition==False and timeOut==False):
            temp_actual = self.getFPAtemp()
            time_values.append(time.time()-t0)
            temp_values.append(temp_actual)
            # condition = temp_actual<=FPA_temp_tolerance_max[n] and temp_actual>=FPA_temp_tolerance_min[n] 
            condition = abs(self.getFPAtemp() - FPA_temp_setpoint) < .2
            print(f"Current temp (oC): {temp_actual}, Set-point: {FPA_temp_setpoint} - delta: {(temp_actual-FPA_temp_setpoint):.1f}     ", end="\r") 
            time.sleep(.5)
            temp_actual = self.getFPAtemp()
            condition = temp_actual<=FPA_temp_tolerance_max[n] and temp_actual>=FPA_temp_tolerance_min[n] 
            print(f"Current temp (oC): {temp_actual}, Set-point: {FPA_temp_setpoint} - delta: {(temp_actual-FPA_temp_setpoint):.1f} ...", end="\r") 
            time.sleep(.5)
            if time.time()-t0 > 60: 
                timeOut=True
                print("Warning: TEC failed to achieve setpoint temperature!!!")
                print("Review TEC parameters:")
                self.getTECparam()
        time.sleep(1)
        if plot == True:
            fig, ax = plt.subplots()
            ax.set_xlabel('Time (s)')
            ax.set_ylabel('FPA Temperature (oC)')
            ax.plot(time_values, temp_values, color='blue')

    def getFPS(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","0114","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-FPS")

    def getPriority(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","0112011A00000000","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-Priority")
        
    def getTECparam(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand,"ED","0113","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        self._decode_tau_response(hex_response, "get-TEC-param")

    def getFPAtemp(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand, "20","0000","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-FPA-temp")
    
    def getSerialNumber(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand, "04","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-serial-number")
    
    def getCMOSBitDepth(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand, "12","0800","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-CMOS-bit-depth")

    def getSensorGain(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand, "ED","0112001400000000","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-Gain")

    def getIntTime(self):
        ans = subprocess.run(["ssh", cameraAddress, cameraCommand, "A1","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-int-time")
    
    def darkFrameMeanCounts(self):
        darkCurrent = self.darkCurrentDensity * 1e-9 * self.detectorArea_cm2 * 6.242e18 # e-/s/px
        electrons =  self.intTime_ms * 1e-3 * darkCurrent
        counts = round(electrons/self.quantizationStepSize)
        if counts > (2**self.digitization): counts = 2**self.digitization - 1
        return counts
    
    def getNoiseCount_Std(self):
        if self.gainMode == "high":
            NEI_ref = self.ref_NEI_highGain   # photons/cm2/s
            t_ref = self.ref_IntTime_highGain #ms
        elif self.gainMode == "medium":
            NEI_ref = self.ref_NEI_highGain   # photons/cm2/s
            t_ref = self.ref_IntTime_highGain #ms
        elif self.gainMode == "low":
            NEI_ref = self.ref_NEI_lowGain   # photons/cm2/s
            t_ref = self.ref_IntTime_lowGain #ms

        NEI_electronsFlux = NEI_ref * self.detectorArea_cm2 * self.QE * math.sqrt(t_ref/self.intTime_ms) # e-/s
        NOISE_electrons = NEI_electronsFlux * self.intTime_ms * 1e-3 # e-
        counts = round(NOISE_electrons/self.quantizationStepSize)
        return counts

    def collectFrame(self, numFrames, filename = "", returnFPAtemp = False):
        # Open the stream of data
        stream = socket(AF_INET, SOCK_STREAM)
        stream.connect((self.hostname, self.port))
        msg = Message(stream)
        # Collect frames
        N = 0
        imglist = []
        fpaTemp = np.array([])
        
        while N < numFrames+1: # (Bruno) I added one to skip the first frame (because it's usually bad)
            if not msg.decode(): continue
            frame = _process_message(msg.buffer)

            if 'SWIR' in frame:
                N +=1
                if N==1: # Skip the first frame
                    continue
                imglist.append(frame["SWIR"])
                if returnFPAtemp == True:
                    temp_actual = self.getFPAtemp()
                    fpaTemp = np.append(fpaTemp, temp_actual)
            elif 'Queue_Length' in frame:
                if frame['Queue_Length']>100:
                    print(f"WARNING: Possible sync error! Queue Usage: {frame['Queue_Length']}MB")

        # Close the stream of data
        # print(" ")
        stream.close()
        if returnFPAtemp == True:
            return np.stack(imglist), fpaTemp
        else:
            return np.stack(imglist)


