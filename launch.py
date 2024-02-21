#!/usr/bin/env python3

from PIL import Image

from tauSWIRcamera import tauSWIRcamera
from analysis import runDarkFrameAnalysis
import numpy as np
 

if __name__ == '__main__':
    hostname = '129.123.5.125'
    port = 4000

    cam = tauSWIRcamera("Industrial", hostname, port)

    # Set FPA temperature to 20C
    cam.setFPATempSetPoint(1)

    runDarkFrameAnalysis(cam, ["low"])

    # cam.collectFrame()

    # cam.setSensorGain("high")

    # cam.setIntTime(10)

    # cam.getSensorGain()
    
    # runDarkFrameAnalysis()


