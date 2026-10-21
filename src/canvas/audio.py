"""
src.canvas.audio
================
Ultra-lightweight background audio consumer for the desktop canvas visualizer.

Ported directly from ``~/.config/desktop-clock.py`` (``audio_worker`` /
``animate_visualizer`` methods) with the following improvements:

* **Thread-safe bar access** via a ``threading.Lock``-protected copy.
* **Clean start/stop lifecycle** with a ``threading.Event`` stop flag.
* **No global state** — everything lives inside :class:`AudioStream`.
* **Configurable** band count, decay constants, and intensity.

Audio source
------------
Identical to the reference script:

1. Query the default PulseAudio sink with ``pactl get-default-sink``.
2. Append ``.monitor`` to get the loopback capture device.
3. Spawn ``parec --format=s16le --rate=22050 --channels=1 -d <monitor>``
   which streams raw signed-16 bit PCM into a pipe.
4. Read 1 024-sample chunks, FFT with a Hanning window, bucket into
   logarithmically-spaced frequency bands.

Processing pipeline (reference lines 301–341)
---------------------------------------------
raw PCM int16 → float32 / 32768
→ RMS gate (< 0.010 → silence, clear bars)
→ rfft + Hanning window
→ log-spaced band averaging
→ adaptive peak normalisation (slow decay)
→ power-curve shaping (^1.30)
→ intensity scaling
→ tapered weighting (high-freq roll-off)
→ exponential smoothing (α = 0.42)
→ mirror into symmetrical left/right wings

Output
------
:attr:`AudioStream.bars` — a ``numpy.ndarray`` of shape ``(total_bars,)``
with values in ``[0.0, 1.0]``.  Read from the GTK draw thread; written by
the audio thread.  Protected by :attr:`AudioStream.lock`.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Number of frequency bands on each half of the symmetric visualizer.
# Reference: NUM_BANDS = 14  → total_bars = 27
NUM_BANDS: int = 14

# Exponential smoothing factor for the frequency bands (reference: 0.42).
# Higher → faster response; lower → smoother.
_ALPHA: float = 0.42

# Peak decay rate per chunk (reference: 0.982).
_PEAK_DECAY: float = 0.982

# RMS silence gate — chunks below this are treated as silence.
_RMS_GATE: float = 0.010

# parec capture parameters (must match the reference exactly).
_SAMPLE_RATE: int = 22_050
_CHUNK_SAMPLES: int = 1_024
_BYTES_PER_SAMPLE: int = 2   # s16le = 2 bytes


class AudioStream:
    """
    Background thread that reads PulseAudio monitor PCM, runs an FFT
    pipeline, and exposes normalized bar heights as a numpy array.

    Parameters
    ----------
    num_bands:
        Number of frequency bands on each side of the symmetric visualizer.
        Default 14 → 27 total bars (mirrors reference NUM_BANDS).
    intensity:
        Height multiplier.  0.30 is the reference default
        (``34 px × (intensity / 0.30)`` in the original).
    """

    def __init__(
        self,
        num_bands: int = NUM_BANDS,
        intensity: float = 0.30,
    ) -> None:
        self.num_bands = num_bands
        self.total_bars = (num_bands * 2) - 1
        self.intensity = intensity

        # Public bar data — the draw thread reads these.
        # Values: 0.0 … 1.0 (already normalised; caller can multiply by px height)
        self.bars: np.ndarray = np.zeros(self.total_bars, dtype=np.float32)
        self.lock = threading.Lock()

        # Internal smoothed bands (not yet mirrored).
        self._smoothed: np.ndarray = np.zeros(num_bands, dtype=np.float32)
        self._peak_level: float = 0.025

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Launch the background audio capture thread.

        Safe to call multiple times — subsequent calls are no-ops if the
        thread is already running.
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="audio-stream",
            daemon=True,
        )
        self._thread.start()
        log.info("AudioStream started (bands=%d, intensity=%.2f)",
                 self.num_bands, self.intensity)

    def stop(self) -> None:
        """
        Signal the audio thread to exit and wait for it to finish.

        Also terminates the ``parec`` subprocess.
        """
        self._stop_event.set()
        self._kill_proc()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        with self.lock:
            self.bars[:] = 0.0
            self._smoothed[:] = 0.0
        log.info("AudioStream stopped")

    def set_intensity(self, val: float) -> None:
        """Update visualizer intensity scaling on the fly without thread restart."""
        self.intensity = max(0.1, min(2.0, float(val)))
        log.debug("AudioStream: intensity updated to %.2f", self.intensity)

    @property
    def is_running(self) -> bool:
        """``True`` if the capture thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal — audio capture thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Entry point for the background thread."""
        monitor = self._detect_monitor()
        proc = self._spawn_parec(monitor)
        if proc is None:
            log.error("AudioStream: could not start parec — visualizer disabled")
            return

        self._proc = proc
        bytes_to_read = _CHUNK_SAMPLES * _BYTES_PER_SAMPLE
        hanning_win = np.hanning(_CHUNK_SAMPLES).astype(np.float32)
        # Pre-compute log-spaced band boundary indices (mirrors reference line 310).
        fft_len = _CHUNK_SAMPLES // 2 + 1
        band_limits = np.logspace(
            np.log10(3), np.log10(fft_len - 1), self.num_bands + 1
        ).astype(int)

        log.info("AudioStream: capture running (monitor=%s)", monitor or "default")

        while not self._stop_event.is_set():
            raw = self._safe_read(proc, bytes_to_read)
            if raw is None:
                break          # parec died or stop requested
            if len(raw) < bytes_to_read:
                time.sleep(0.02)
                continue

            self._process_chunk(raw, hanning_win, band_limits)

        self._kill_proc()

    def _process_chunk(
        self,
        raw: bytes,
        hanning_win: np.ndarray,
        band_limits: np.ndarray,
    ) -> None:
        """
        FFT pipeline — direct port of reference lines 301–341.

        Converts *raw* PCM bytes → normalised bar heights, stored in
        :attr:`bars` under :attr:`lock`.
        """
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        # RMS silence gate (reference line 304).
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if rms < _RMS_GATE:
            with self.lock:
                self.bars[:] = 0.0
                self._smoothed[:] = 0.0
            return

        # FFT with Hanning window (reference line 309).
        spectrum = np.abs(np.fft.rfft(samples * hanning_win)) / (_CHUNK_SAMPLES / 2)

        # Log-spaced band averaging (reference lines 313–318).
        raw_bands = np.zeros(self.num_bands, dtype=np.float32)
        for i in range(self.num_bands):
            st = band_limits[i]
            en = band_limits[i + 1]
            if en <= st:
                en = st + 1
            raw_bands[i] = float(np.mean(spectrum[st:en]))

        # Adaptive peak normalisation (reference lines 320–324).
        cur_max = float(np.max(raw_bands))
        if cur_max > self._peak_level:
            self._peak_level = cur_max
        else:
            self._peak_level = max(0.025, self._peak_level * _PEAK_DECAY)

        # Normalise + power-curve shaping (reference lines 326–327).
        norm = np.clip(raw_bands / (self._peak_level + 1e-4), 0.0, 1.0)
        shaped = np.power(norm, 1.30)

        # Intensity scaling (reference lines 330–331).
        max_ceiling = self.intensity / 0.30   # normalised so 0.30 → 1.0
        scaled = shaped * max_ceiling

        # Taper: high-frequency roll-off (reference lines 334–335).
        taper = np.linspace(1.20, 0.60, self.num_bands, dtype=np.float32)
        scaled = scaled * taper

        # Exponential smoothing (reference line 337).
        self._smoothed = _ALPHA * scaled + (1.0 - _ALPHA) * self._smoothed

        # Mirror into symmetric left/right wings (reference lines 339–341).
        left_wing  = self._smoothed[1:][::-1]
        right_wing = self._smoothed[1:]
        mirrored   = np.concatenate([left_wing, [self._smoothed[0]], right_wing])

        # Clamp to [0, 1] for the draw cycle.
        mirrored = np.clip(mirrored, 0.0, 1.0)

        with self.lock:
            self.bars[:] = mirrored

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_monitor() -> Optional[str]:
        """
        Return the PulseAudio monitor source name.

        Mirrors reference lines 275–279:
        ``sink = pactl get-default-sink; monitor = f"{sink}.monitor"``
        """
        try:
            out = subprocess.check_output(
                ["pactl", "get-default-sink"],
                stderr=subprocess.DEVNULL,
                timeout=3.0,
            ).decode().strip()
            if out:
                return f"{out}.monitor"
        except Exception as exc:
            log.debug("_detect_monitor: %s", exc)
        return None

    @staticmethod
    def _spawn_parec(monitor: Optional[str]) -> Optional[subprocess.Popen]:
        """
        Spawn ``parec`` with the same arguments as the reference script
        (lines 282–290).
        """
        cmd = [
            "parec",
            f"--format=s16le",
            f"--rate={_SAMPLE_RATE}",
            "--channels=1",
        ]
        if monitor:
            cmd.extend(["-d", monitor])
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.error("parec not found — install pulseaudio-utils")
            return None
        except Exception as exc:
            log.error("Could not spawn parec: %s", exc)
            return None

    def _safe_read(self, proc: subprocess.Popen, n: int) -> Optional[bytes]:
        """Read *n* bytes from *proc*.stdout, returning None on error/stop."""
        try:
            data = proc.stdout.read(n)
            if self._stop_event.is_set():
                return None
            return data
        except Exception:
            return None

    def _kill_proc(self) -> None:
        """Terminate the parec subprocess if it is still alive."""
        p = self._proc
        self._proc = None
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=2.0)
            except Exception:
                pass

    def __repr__(self) -> str:  # pragma: no cover
        state = "running" if self.is_running else "stopped"
        return (
            f"AudioStream(bands={self.num_bands}, intensity={self.intensity:.2f}, "
            f"{state})"
        )
