#!/bin/bash
if pgrep -f "mpv-livewal.sock" >/dev/null 2>&1 || pgrep -f "xwinwrap" >/dev/null 2>&1; then
    killall xwinwrap 2>/dev/null
    pkill -f "mpv-livewal.sock" 2>/dev/null
    pkill -f "live-wallpaper-daemon.sh" 2>/dev/null
    rm -f /tmp/mpv-livewal.sock
else
    /home/mint/.local/bin/live-wallpaper-daemon.sh &
fi
