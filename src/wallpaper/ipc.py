"""
src.wallpaper.ipc
=================
Lightweight Unix-domain-socket client for the mpv JSON IPC server.

The daemon exposes a socket at ``/tmp/mpv-livewal.sock``.  This module
replaces the ``socat`` one-liners from ``daemon_current.sh``::

    echo '{ "command": ["set_property", "pause", true] }' | socat - "$SOCK"

with a proper Python client that:

* Opens a **fresh connection per command** (stateless, just like socat) so
  a dead socket never blocks the rest of the app.
* Applies a short connect/read timeout so the caller is never blocked more
  than ``timeout`` seconds.
* Swallows all socket-level errors and returns ``None`` / ``False`` instead
  of raising, making it safe to call even when mpv is not running.

Reference
---------
* daemon_current.sh lines 61–63: IPC command format
* mpv JSON IPC docs: https://mpv.io/manual/master/#json-ipc
"""

from __future__ import annotations

import json
import socket
import os
import errno
import logging
from typing import Any

log = logging.getLogger(__name__)

# Default path matches daemon_current.sh: SOCK="/tmp/mpv-livewal.sock"
MPV_SOCKET: str = "/tmp/mpv-livewal.sock"

# Maximum seconds to wait for a connect or response.
_TIMEOUT: float = 1.0

# Maximum bytes to read back from a single command response.
_RECV_SIZE: int = 4096


class MpvIPC:
    """
    Stateless client for mpv's Unix-domain-socket JSON IPC interface.

    Every public method opens a fresh socket connection, sends one JSON
    command, optionally reads the response, then closes the connection.
    This mirrors what the reference daemon does with ``socat``.

    Parameters
    ----------
    socket_path:
        Path to the mpv IPC socket.  Defaults to ``/tmp/mpv-livewal.sock``.
    timeout:
        Connect and read timeout in seconds.
    """

    def __init__(
        self,
        socket_path: str = MPV_SOCKET,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Core send / receive
    # ------------------------------------------------------------------

    def send_command(self, cmd_list: list[Any]) -> dict | None:
        """
        Send a JSON IPC command and return the parsed response dict.

        Parameters
        ----------
        cmd_list:
            The value of the ``"command"`` key, e.g.
            ``["set_property", "pause", True]``.

        Returns
        -------
        dict
            The parsed mpv JSON response, or ``None`` on any error
            (socket missing, timeout, decode error, …).

        Examples
        --------
        ::

            ipc.send_command(["set_property", "pause", True])
            ipc.send_command(["get_property", "playback-time"])
        """
        payload = json.dumps({"command": cmd_list}) + "\n"
        return self._send_raw(payload.encode())

    def _send_raw(self, data: bytes) -> dict | None:
        """Open a fresh socket, write *data*, read one response line."""
        if not os.path.exists(self.socket_path):
            log.debug("IPC socket not found: %s", self.socket_path)
            return None

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                sock.connect(self.socket_path)
                sock.sendall(data)
                # mpv writes one JSON object per line; read until newline.
                response = b""
                while b"\n" not in response:
                    chunk = sock.recv(_RECV_SIZE)
                    if not chunk:
                        break
                    response += chunk
            finally:
                sock.close()
        except OSError as exc:
            # ECONNREFUSED  → mpv just died
            # ENOENT        → socket deleted between our check and connect
            # timeout       → mpv frozen / busy
            if exc.errno not in (errno.ECONNREFUSED, errno.ENOENT, None):
                log.warning("IPC send error (%s): %s", type(exc).__name__, exc)
            return None

        # Parse the first complete JSON line.
        line = response.split(b"\n")[0].strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            log.debug("IPC response parse error: %s — raw: %r", exc, line)
            return None

    # ------------------------------------------------------------------
    # Convenience wrappers (mirror daemon socat one-liners)
    # ------------------------------------------------------------------

    def pause(self) -> bool:
        """
        Tell mpv to pause playback.

        Equivalent to::

            echo '{"command":["set_property","pause",true]}' | socat - "$SOCK"

        Returns ``True`` if the command was accepted (no socket error).
        """
        result = self.send_command(["set_property", "pause", True])
        return result is not None

    def resume(self) -> bool:
        """
        Tell mpv to resume playback.

        Equivalent to::

            echo '{"command":["set_property","pause",false]}' | socat - "$SOCK"
        """
        result = self.send_command(["set_property", "pause", False])
        return result is not None

    def set_volume(self, val: int) -> bool:
        """
        Set mpv's volume (0–100).

        Parameters
        ----------
        val:
            Integer volume level, clamped to [0, 100].
        """
        val = max(0, min(100, int(val)))
        result = self.send_command(["set_property", "volume", val])
        return result is not None

    def set_speed(self, val: float) -> bool:
        """
        Set mpv's playback speed multiplier (0.25 – 2.0).

        Parameters
        ----------
        val:
            Speed multiplier.  Values outside [0.01, 100.0] are clamped.
        """
        val = max(0.01, min(100.0, float(val)))
        result = self.send_command(["set_property", "speed", val])
        return result is not None

    def get_property(self, name: str) -> Any:
        """
        Query a mpv property.

        Returns the ``"data"`` field of the response, or ``None`` on error.
        """
        result = self.send_command(["get_property", name])
        if result and result.get("error") == "success":
            return result.get("data")
        return None

    def is_alive(self) -> bool:
        """
        Return ``True`` if the mpv socket exists *and* responds to a ping.

        A socket file can linger on disk after an unclean shutdown; this
        method distinguishes a real live mpv from a stale socket file.
        """
        if not os.path.exists(self.socket_path):
            return False
        # Use get_property "pid" as a lightweight ping — mpv always responds.
        result = self.send_command(["get_property", "pid"])
        return result is not None and result.get("error") == "success"

    def __repr__(self) -> str:  # pragma: no cover
        return f"MpvIPC(socket={self.socket_path!r}, timeout={self.timeout})"
