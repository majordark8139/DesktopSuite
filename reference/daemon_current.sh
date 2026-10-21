#!/bin/bash
CONF="$HOME/.config/live-wallpaper.conf"
SOCK="/tmp/mpv-livewal.sock"
VIDEO=""; AUTOPAUSE="focus"; FPS="native"; FIT="fill"; SPEED="1.0"; MUTE="yes"; VOL="50"; OPACITY="1.0"
[ -f "$CONF" ] && source "$CONF"
[ -z "$VIDEO" ] || [ ! -f "$VIDEO" ] && exit 1

# Kill previous instances cleanly
killall xwinwrap 2>/dev/null
pkill -f "mpv-livewal.sock" 2>/dev/null
rm -f "$SOCK"

# Clean exit trap
cleanup() {
    kill "$WPID" "$XPID" 2>/dev/null
    killall xwinwrap 2>/dev/null
    pkill -f "mpv-livewal.sock" 2>/dev/null
    rm -f "$SOCK"
    exit 0
}
trap cleanup INT TERM EXIT

ARGS=(-wid WID --loop=inf --vo=gpu --hwdec=vaapi --cache=no --demuxer-max-bytes=15M --no-osc --no-osd-bar --speed="$SPEED" --volume="$VOL" --input-ipc-server="$SOCK")
[ "$MUTE" = "yes" ] && ARGS+=(--no-audio)
[ "$FIT" = "fill" ] && ARGS+=(--panscan=1.0)
[ "$FIT" = "fit" ] && ARGS+=(--panscan=0.0)
[ "$FIT" = "stretch" ] && ARGS+=(--keepaspect=no)
[ "$FPS" != "native" ] && ARGS+=(--vf=fps="$FPS")

xwinwrap -fs -ni -s -st -sp -b -nf -un -- mpv "${ARGS[@]}" "$VIDEO" >/dev/null 2>&1 &
XPID=$!

# Wait for mpv IPC socket
for i in {1..25}; do [ -S "$SOCK" ] && break; sleep 0.1; done

# Auto-pause watcher loop
if [ "$AUTOPAUSE" != "off" ]; then
    (
        PAUSED=0
        while true; do
            WIN=$(xdotool getactivewindow 2>/dev/null)
            PAUSE=0

            if [ -n "$WIN" ] && [ "$WIN" != "0" ]; then
                CLS=$(xprop -id "$WIN" WM_CLASS 2>/dev/null)
                # Keep playing on desktop or clock
                if ! echo "$CLS" | grep -qiE "xfdesktop|desktop-clock|plank"; then
                    if [ "$AUTOPAUSE" = "focus" ]; then
                        PAUSE=1
                    elif [ "$AUTOPAUSE" = "maximized" ]; then
                        STATE=$(xprop -id "$WIN" _NET_WM_STATE 2>/dev/null)
                        if echo "$STATE" | grep -qE "MAXIMIZED_VERT|MAXIMIZED_HORZ|FULLSCREEN"; then
                            PAUSE=1
                        fi
                    fi
                fi
            fi

            if [ "$PAUSE" != "$PAUSED" ]; then
                if [ "$PAUSE" -eq 1 ]; then
                    echo '{ "command": ["set_property", "pause", true] }' | socat - "$SOCK" 2>/dev/null
                else
                    echo '{ "command": ["set_property", "pause", false] }' | socat - "$SOCK" 2>/dev/null
                fi
                PAUSED=$PAUSE
            fi
            sleep 0.4
        done
    ) &
    WPID=$!
fi

wait "$XPID"
