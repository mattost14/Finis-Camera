import numpy as np
import matplotlib.pyplot as plt
from tauSWIRcamera import tauSWIRcamera
plt.rcParams["font.family"] = "Times New Roman"

def runDarkFrameAnalysis(cam: tauSWIRcamera, gainModes = ["high","medium","low"], intTime_ms = np.linspace(1,15,15)):
    # Dark frame collection and statistical analysis
    fig, ax = plt.subplots()
    for gain in gainModes:
        cam.setSensorGain(gain)
        df_mean  = np.array([])
        df_mean_estimated = np.array([])
        df_std  = np.array([])
        df_estimated_std = np.array([])
        for t_ms in intTime_ms:
            # Set Integration Time
            print(f"Set integration time to {t_ms}")
            cam.setIntTime(t_ms)
            # Collect frames
            df = np.stack(cam.collectFrame(10))
            # Remove outliers
            mask_deadPixels = abs(df.mean(axis=0)-df.mean()) > 5*df.std()
            numDeadPixels = np.sum(mask_deadPixels)
            # Recompute mean and std ignoring the dead pixels
            # Apply the mask to the stack of arrays
            # Repeat the 2D mask along the third dimension to make it compatible with the 3D array
            mask_deadPixels_stack = np.tile(mask_deadPixels[None, :, :], (df.shape[0], 1, 1))
            masked_df= np.ma.masked_array(df, mask_deadPixels_stack)

            df_mean = np.append(df_mean, np.mean(masked_df))
            df_std = np.append(df_std, np.std(masked_df))

            df_mean_estimated = np.append(df_mean_estimated, cam.darkFrameMeanCounts())
            df_estimated_std = np.append(df_estimated_std, cam.getNoiseCount_Std())
            print(f"Num of dead pixels: {numDeadPixels}")
            print(f"mean: {round(np.mean(masked_df))}, std: {round(np.std(masked_df))}")
            print(" ")
        # Plot results
        ax.errorbar(intTime_ms, df_mean-df_mean[0], yerr=df_std, label=f"Measured ({gain} gain)", capsize=10, marker='o', markersize=5)
        ax.errorbar(intTime_ms, df_mean_estimated-df_mean_estimated[0], yerr=df_estimated_std, label=f"Estimated ({gain} gain)", capsize=10, marker='*', markersize=5)
    plt.suptitle(f"Dark current analysis", fontsize = 16, fontweight="bold")
    plt.title(f"Tau SWIR camera ({cam.model}) - FPA temp: {cam.getFPAtemp()}\N{DEGREE SIGN}C")
    plt.ylabel("Counts")
    plt.xlabel("Integration time (ms)")
    plt.legend()   
    plt.grid() 
    plt.show()