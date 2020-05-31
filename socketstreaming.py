import itertools
import json
import matplotlib.pyplot as plt
import socket
import time
import logging
logging.basicConfig(level=logging.DEBUG)


# constants
CHANNELS = 8  # number of eeg channels
PLOT_MEMO = 0.5  # plot memory in seconds
SR = 222  # expected sampling rate/frequency (Hz): N/elapsed_time
SI = 4.5  # expected sampling interval (ms): 1/SR
C_SR = True  # set constant or not constant sampling rate


## Plot definiton
fig = plt.gcf()
plt.ion()  # not sure if necessary, also works without
plt.style.use("ggplot")  # use ggplot style

# color iterable from a color map
color = itertools.cycle(plt.get_cmap("tab10").colors)

# prepare the lines to plot with their labels and colors
for i in range(CHANNELS):
    c = next(color)  # get next color from the palette (color map)
    plt.plot([],[], color=c, linewidth=0.6, linestyle="-", label=f"ch-{i + 1}")

ax = plt.gca()  # get axis
box = ax.get_position()  # box position to shrink axis
lines = [line for line in ax.lines]  # unpack the lines
# manually set visible y-axis limits
ax.set_ylim(-2000, 2000)  # can also be updated according to min/max amplitude
plt.tight_layout()
plt.legend(loc="center left", bbox_to_anchor=(1, 0.5))  # legend position
plt.xlabel("Time (s)")
plt.ylabel("Voltage (μV)")
fig.show()


# dict to organize the data to plot into lines
eeg = {f"ch-{i + 1}": {"series": []} for i in range(CHANNELS)}
eeg["time"] = []
"""
Example:
    stored = {
        "time": [timestamps]
        "ch-1": { "series": [ch-1 amplitudes] }
        "ch-2": { "series": [ch-2 amplitudes] }
        ...
    }
"""

# vars to manipulate while plotting
c_time = 0
first = 0


# TODO: improve autoscale_view and relim to have fixed grid (or set xlim manually)
Just selected fewer data.

#TODO Switch to numpy arrays. 

# TODO: separate storing than plotting data, start plotting when there's enoug data and plot @ 25-30FPS (e.g. store data dict by dict received, plot 25-30 times a second)
def update_lines(xwindow=1000):
    global lines, SI
    
    # That means xwindow/2 / c_si
    windowsize= int(xwindow / SI)
    
    logging.debug(f"Len of eeg[time]: {len(eeg['time'])} windowsize: {windowsize}")
    if len(eeg["time"]) <= windowsize:
        return
    times = eeg["time"][-windowsize:]  # all time values
    
     
    for i in range(CHANNELS):
        key = f"ch-{i+1}" # selected amplitude values
        series = eeg[key]["series"][-windowsize:]
        lines[i].set_data(times, series)  # update lines time-series data
    
    # shrink current axis by 5% to place legend out of plot box
    ax.set_position([box.x0, box.y0, box.width * 0.95, box.height])
    # ax.set_ylim(ymin - EXTRA_YLIM, ymax + EXTRA_YLIM)
    
    plt.title(f"Traumschreiber EEG streaming @ {sampling_rate} Hz")
    # recompute the ax.dataLim
    ax.relim()
    # update ax.viewLim using the new dataLim
    ax.autoscale_view(True, True, True)
    fig.canvas.draw()
    fig.canvas.flush_events()

def store_data(ddict, constant=False):
    global first, c_time
    # organize the data to plot a line per channel
    if not constant:
        timestamp = ddict["time"] / 1000  # get timestamp in s
        if first == 0:  # first timestamp
            first = timestamp  # store it for time reference
        # calculate time relative to first timestamp (so starting at 0)
        time = timestamp - first
    else:
        # assuming constant sampling interval
        c_time += SI / 1000
        time = c_time
    eeg["time"].append(time)  # add time
    
    
    for i in range(CHANNELS):  # each channel
        key = str(i + 1)  # as keys on eeg are 1-8
        series = ddict[key]  # eeg amplitude value
        eeg[f"ch-{key}"]["series"].append(series)  # add eeg amplitude
    # call update plot when packages >= 111 (expected samples in 0.5s)
    if len(eeg["time"]) >= SR / 2:
        update_lines()

def build_connection(host="",port=65432):
    ss = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # reuse address:port if on use
        # otherwise process needs to be killed if socket wasn't closed
        ss.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ss.bind((host, port))  # associate the socket with an address and port
    except socket.error as e:
        print(str(e))
        
    print("Waiting for a Connection..")
    ss.listen()  # listening socket, ready to accept connections

    c, address = ss.accept()  # wait for incoming connections
    ip = address[0]  # socket sender IP
    port = address[1]  # socket sender port
    print(f"Connected to {ip}:{port}")
    
    return ss,c


ss,c = build_connection()

# vars to handle the receiving data loop
start = False
end = True
chunks = ""
no_data = 0  # no incoming data counter


# starting time reference for elapsed time and sampling rate calculations
t_start = None
pkg = 0
sampling_rate = 0  # calculated SR

# loop for handling incoming data
while True:  
    
    # Calculate Elapsed Time
    ## Set Start Time
    if not t_start:  # reference timestamp not set
        t_start = time.time()  # reference timestamp (ms)
    
    t_now = time.time()  # timestamp (ms)
    elapsed = t_now - t_start    
    
    # read and decode incoming data (buffer of 1 byte)
    response = c.recv(1).decode("utf-8")
    
    # First Case: Empty Response
    if len(response) <= 0:  # no incoming data
        no_data += 1  # increase empty response count
        if no_data > 10000:  # sending socket stops sending
            break  # break loop
            
    # Second Case: We read the first byte of actual data
    elif not start:
        if response == "{":  # stringified JSON dict start
            chunks += response  # add chunk
            start = True  # dict start found flag
            end = False  # look for the rest flag
            no_data = 0  # reset no incoming data counter
    
    # Third Case: We read any other of the sent bytes
    elif not end:
        
        # Chunk is not completed yet
        if response != "}":  # stringified JSON dict end
            chunks += response
        
        # Chunk is finished
        else:
            chunks += response
            end = True  # dict start found flag
            start = False  # look for the start flag
            # remove ending breaklines, remove starting and ending whitespaces
            message = chunks.rstrip("\n").strip()
            chunks = ""  # clear accumulated chunks
            current = json.loads(message)  # parse stringified JSON as dict
            store_data(current, C_SR)  # add current read package for plotting
            pkg += 1
            elapsed += 1
            sampling_rate = int(pkg  / elapsed) 
            # calculate sampling rate 
            # print(current)  # current received data {pkg, time, ch1-8}
            no_data = 0

ss.close()  # disconnect listening socket
print("Socket closed")