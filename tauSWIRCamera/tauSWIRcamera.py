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
    _validGainModes = ["high","medium","low"]
    _wellSizes = {"low": 1.38e6, "medium" : 118e3, "high": 41e3}


    def __init__(self, model, hostname, port, gainMode = "low"):
        if model not in ["Industrial", "Performance", "Commercial"]: 
            raise "Invalid model name! Options: Industrial, Performance or Commercial"
        else:
            self.model = model
            self.gainMode = gainMode
            self.hostname = hostname
            self.port = port
            self.wellSize = self._wellSizes[gainMode]
            self.quantizationStepSize = self.wellSize / (2**self.digitization)
            self._runSetupScript()
            self._setupParameters()
            self.intTime_ms = self.getIntTime()

    def _setupParameters(self):
        if self.model == "Industrial":
            self.darkCurrentDensity = 10; # nA/cm2 
            self.ref_IntTime_lowGain = 1 # ms  
            self.ref_IntTime_highGain = 33 # ms 
            self.ref_NEI_lowGain = 7.12e11  # photons cm^-2s^-1
            self.ref_NEI_highGain = 1.78e9  # photons cm^-2s^-1
        elif self.model == "Performance":
            self.darkCurrentDensity = 50; # nA/cm2 
            self.ref_IntTime_lowGain = 1 # ms 
            self.ref_IntTime_highGain = 5 # ms 
            self.ref_NEI_lowGain = 7.13e11  # photons cm^-2s^-1    (WE DO NOT KNOW THIS!)
            self.ref_NEI_highGain = 1.03e10  # photons cm^-2s^-1   (WE DO NOT KNOW THIS!)
        elif self.model == "Commercial":
            self.darkCurrentDensity = 100; # nA/cm2 
            self.ref_IntTime_lowGain = 1 # ms 
            self.ref_IntTime_highGain = 2 # ms
            self.ref_NEI_lowGain = 7.13e11  # photons cm^-2s^-1
            self.ref_NEI_highGain = 2.36e10  # photons cm^-2s^-1
    
    def setSensorGain(self, gainMode):
        if gainMode not in self._validGainModes: 
            raise "Invalid gain mode. Options: high, medium, low"
        else:
            self.gainMode = gainMode
            self._runSetupScript()
            # Now check if the gain change was accepted
            if self.getSensorGain() == gainMode : 
                self.wellSize = self._wellSizes[gainMode]
                self.quantizationStepSize = self.wellSize / (2**self.digitization)
                print(f"Gain set to: {gainMode} - Wellsize: {self.wellSize} e-")
            else:
                raise "Error on setting the gain!"
            
    def setIntTime(self, int_time_ms):
        subprocess.run(["ssh", "rroci@129.123.5.125", "./setIntTime.sh", str(int_time_ms)], capture_output=True)
        time.sleep(2/30)
        # Now check if the gain change was accepted
        intTimeFromCamera = self.getIntTime()
        if abs(intTimeFromCamera - int_time_ms)/int_time_ms < 0.01 : # Tolerate 1% difference
            print(f"Int. Time set to: {intTimeFromCamera:.2f}ms")
            self.intTime_ms = intTimeFromCamera
        else:
            raise "Error on setting the integration time!"
        
    def setFPATempSetPoint(self,n, plot=False):
        # The temperature setpoint is set based on the information provided in the "Table 3-4, TEC Control Table Showing Default Values", page 17 of the Tau-Swir-Product-specificaiton
        FPA_temp_setpoint_options = [0, 20, 40, 45] #oC
        FPA_temp_tolerance_max = [2,22,42, 75] #oC
        FPA_temp_tolerance_min = [-40,18,38,43] #oC
        FPA_temp_setpoint = FPA_temp_setpoint_options[n]
        print("Previous TEC parameters:")
        self.getTECparam()
        subprocess.run(["ssh", "rroci@129.123.5.125", "taucmd -f /dev/ttyUSB0","ED",f"020F0001000{n}","-d 2"], capture_output=True)
        time.sleep(2/30)
        # Now check if the set point was accepted
        print("New TEC parameters:")
        self.getTECparam()
        # Wait until temperature is close to set point
        temp_actual = self.getFPAtemp()
        condition = temp_actual<=FPA_temp_tolerance_max[n] and temp_actual>=FPA_temp_tolerance_min[n] 
        t0 = time.time()
        timeOut = False
        temp_values = []
        time_values = []

        while(condition==False and timeOut==False):
            temp_actual = self.getFPAtemp()
            time_values.append(time.time()-t0)
            temp_values.append(temp_actual)
            condition = temp_actual<=FPA_temp_tolerance_max[n] and temp_actual>=FPA_temp_tolerance_min[n] 
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
        if plot == True:
            fig, ax = plt.subplots()
            ax.set_xlabel('Time (s)')
            ax.set_ylabel('FPA Temperature (oC)')
            ax.plot(time_values, temp_values, color='blue')
        
    def getTECparam(self):
      ans = subprocess.run(["ssh", "rroci@129.123.5.125", "taucmd -f /dev/ttyUSB0","ED","0113","-d 2"], capture_output=True)
      hex_response = extract_hex_values_from_response(ans.stderr.decode())
      self._decode_tau_response(hex_response, "get-TEC-param")

    def getFPAtemp(self):
        ans = subprocess.run(["ssh", "rroci@129.123.5.125", "taucmd -f /dev/ttyUSB0", "20","0000","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-FPA-temp")

    def _runSetupScript(self):
        print(f"Running setup script - Gain Mode: {self.gainMode}")
        subprocess.run(["ssh", "rroci@129.123.5.125", "./finis_setup.sh", self.gainMode], capture_output=True)
        time.sleep(2/30)

    def getSensorGain(self):
        ans = subprocess.run(["ssh", "rroci@129.123.5.125", "taucmd -f /dev/ttyUSB0", "ED","0112001400000000","-d 2"], capture_output=True)
        hex_response = extract_hex_values_from_response(ans.stderr.decode())
        return self._decode_tau_response(hex_response, "get-Gain")

    def getIntTime(self):
        ans = subprocess.run(["ssh", "rroci@129.123.5.125", "taucmd -f /dev/ttyUSB0", "A1","-d 2"], capture_output=True)
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
            return self._validGainModes[gainN]
        
    def collectFrame(self, numFrames, filename = "", returnFPAtemp = False):
        # Open the stream of data
        stream = socket(AF_INET, SOCK_STREAM)
        stream.connect((self.hostname, self.port))
        msg = Message(stream)
        # Collect frames
        N = 0
        imglist = []
        fpaTemp = np.array([])
        
        while N < numFrames:
            if not msg.decode(): continue
            frame = _process_message(msg.buffer)
            if 'SWIR' in frame:
                N +=1
                # print(f"Frame: {N}/{numFrames}")
                print('.', end='')
                imglist.append(frame["SWIR"])

                if returnFPAtemp == True:
                    temp_actual = self.getFPAtemp()
                    fpaTemp = np.append(fpaTemp, temp_actual)
                # img = Image.fromarray(frame['SWIR'], 'L')
                # img.show()
                # imglist= TiffWriter('images/img.tif')
                # imglist.write(frame["SWIR"], contiguous=True, subfiletype=2)
                # imglist.close()
        # Close the stream of data
        print(" ")
        stream.close()
        if returnFPAtemp == True:
            return np.stack(imglist), fpaTemp
        else:
            return np.stack(imglist)


