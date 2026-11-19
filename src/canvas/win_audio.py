"""
src.canvas.win_audio
====================
Windows WASAPI loopback audio capture for the desktop visualizer.

Captures system audio output (Spotify, YouTube, games, media players) directly
via WASAPI loopback without requiring virtual audio cables, runs an FFT pipeline,
and produces a symmetric 27-bar frequency array matching src/canvas/audio.py.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

NUM_BANDS: int = 14
_ALPHA: float = 0.42
_PEAK_DECAY: float = 0.982
_CHUNK_SAMPLES: int = 1024


class WinAudioStream:
    """
    Background worker thread capturing Windows audio via WASAPI loopback.
    Exposes thread-safe bar heights compatible with DesktopCanvasWindow.
    """

    def __init__(self, num_bands: int = NUM_BANDS, intensity: float = 0.65) -> None:
        self.num_bands = num_bands
        self.total_bars = (num_bands * 2) - 1
        self.intensity = intensity

        self.bars = np.zeros(self.total_bars, dtype=np.float32)
        self.lock = threading.Lock()

        self._smooth_bands = np.zeros(num_bands, dtype=np.float32)
        self._peak_history = 0.05
        self._hanning = np.hanning(_CHUNK_SAMPLES).astype(np.float32)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="win-audio-stream")
        self._thread.start()
        log.info("Windows audio stream thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info("Windows audio stream thread stopped")

    def set_intensity(self, intensity: float) -> None:
        self.intensity = max(0.1, min(2.0, intensity))

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                import soundcard as sc

                speaker = sc.default_speaker()
                if not speaker:
                    log.warning("No default speaker found for WASAPI capture")
                    self._fallback_step()
                    time.sleep(0.5)
                    continue

                native_rate = getattr(speaker, "samplerate", None) or 48000
                loopback_mic = None
                try:
                    loopback_mic = sc.get_microphone(id=speaker.id, include_loopback=True)
                except Exception:
                    pass

                if not loopback_mic:
                    for m in sc.all_microphones(include_loopback=True):
                        if getattr(m, "isloopback", False) and speaker.name in m.name:
                            loopback_mic = m
                            break
                    if not loopback_mic:
                        for m in sc.all_microphones(include_loopback=True):
                            if getattr(m, "isloopback", False):
                                loopback_mic = m
                                break

                if not loopback_mic:
                    log.warning("No loopback microphone endpoint found on WASAPI")
                    self._fallback_step()
                    time.sleep(0.5)
                    continue

                log.info("Starting WASAPI loopback capture on '%s' (%s Hz)", loopback_mic.name, native_rate)
                with loopback_mic.recorder(samplerate=native_rate, blocksize=_CHUNK_SAMPLES) as recorder:
                    while not self._stop_event.is_set():
                        data = recorder.record(numframes=_CHUNK_SAMPLES)
                        if data.ndim > 1 and data.shape[1] > 1:
                            mono_data = np.mean(data, axis=1).astype(np.float32)
                        else:
                            mono_data = data.flatten().astype(np.float32)

                        # Check for silence (pause / muted / inactive)
                        if np.max(np.abs(mono_data)) < 1e-5:
                            with self.lock:
                                self._smooth_bands *= 0.85
                                self._update_bars()
                            continue

                        # Windowed FFT calculation
                        windowed = mono_data[:_CHUNK_SAMPLES] * self._hanning[:len(mono_data)]
                        fft = np.abs(np.fft.rfft(windowed, n=_CHUNK_SAMPLES))[:_CHUNK_SAMPLES // 2]

                        # Group into log-spaced frequency bands across audible range (approx 45 Hz - 18 kHz)
                        freq_bins = np.logspace(0.5, np.log10(len(fft) - 1), self.num_bands + 1).astype(int)
                        band_vals = np.zeros(self.num_bands, dtype=np.float32)
                        for i in range(self.num_bands):
                            lo = max(0, freq_bins[i])
                            hi = max(lo + 1, freq_bins[i + 1])
                            band_vals[i] = float(np.mean(fft[lo:hi]))

                        cur_peak = float(np.max(band_vals))
                        self._peak_history = max(self._peak_history * _PEAK_DECAY, cur_peak, 0.05)
                        normalized = np.clip(band_vals / self._peak_history, 0.0, 1.0)
                        shaped = (normalized ** 1.30) * (self.intensity / 0.30)

                        # High-frequency rolloff compensation
                        weights = np.linspace(1.0, 0.65, self.num_bands, dtype=np.float32)
                        shaped *= weights

                        with self.lock:
                            self._smooth_bands += _ALPHA * (shaped - self._smooth_bands)
                            self._update_bars()

            except Exception as exc:
                log.debug("WASAPI worker loop exception: %s", exc)
                self._fallback_step()
                time.sleep(0.3)

    def _update_bars(self) -> None:
        left = self._smooth_bands[::-1]
        center = self._smooth_bands[0:1]
        right = self._smooth_bands
        combined = np.concatenate([left[:-1], center, right[1:]])
        np.clip(combined, 0.0, 1.0, out=self.bars)

    def _fallback_step(self) -> None:
        with self.lock:
            self._smooth_bands *= 0.85
            self._update_bars()
