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
_RMS_GATE: float = 0.010
_SAMPLE_RATE: int = 22050
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
        has_soundcard = False
        recorder = None
        try:
            import soundcard as sc
            spk = sc.default_speaker()
            loopback_mic = None
            if spk:
                mics = sc.all_microphones(include_loopback=True)
                for m in mics:
                    if getattr(m, "isloopback", False) and spk.name in m.name:
                        loopback_mic = m
                        break
                if not loopback_mic:
                    for m in mics:
                        if getattr(m, "isloopback", False):
                            loopback_mic = m
                            break

            if loopback_mic:
                # Windows 7 WASAPI loopback requires standard device sample rate & stereo (channels=2)
                for sr in (44100, 48000, _SAMPLE_RATE):
                    try:
                        recorder = loopback_mic.recorder(samplerate=sr, channels=2)
                        recorder.__enter__()
                        has_soundcard = True
                        log.info("WASAPI loopback audio recorder initialised on '%s' (%d Hz, 2ch)", loopback_mic.name, sr)
                        break
                    except Exception as sr_exc:
                        log.debug("Failed samplerate %d: %s", sr, sr_exc)
        except Exception as exc:
            log.warning("WASAPI loopback not available (%s); falling back to synthetic generator", exc)

        try:
            while not self._stop_event.is_set():
                if has_soundcard and recorder is not None:
                    try:
                        pcm = recorder.record(numframes=_CHUNK_SAMPLES)
                        # Downmix stereo to mono for FFT pipeline
                        if pcm.ndim > 1 and pcm.shape[1] > 1:
                            chunk = np.mean(pcm, axis=1).astype(np.float32)
                        elif pcm.ndim > 1:
                            chunk = pcm[:, 0].astype(np.float32)
                        else:
                            chunk = pcm.astype(np.float32)
                        self._process_chunk(chunk)
                    except Exception as rec_exc:
                        log.debug("Audio recording error: %s", rec_exc)
                        self._fallback_step()
                else:
                    self._fallback_step()
                    time.sleep(0.033)
        finally:
            if recorder is not None:
                try:
                    recorder.__exit__(None, None, None)
                except Exception:
                    pass

    def _process_chunk(self, chunk: np.ndarray) -> None:
        if len(chunk) < _CHUNK_SAMPLES:
            return

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms < _RMS_GATE:
            with self.lock:
                self._smooth_bands *= 0.75
                self._update_bars()
            return

        windowed = chunk[:_CHUNK_SAMPLES] * self._hanning
        fft = np.abs(np.fft.rfft(windowed))[:_CHUNK_SAMPLES // 2]

        freq_bins = np.logspace(0.5, np.log10(len(fft) - 1), self.num_bands + 1).astype(int)
        band_vals = np.zeros(self.num_bands, dtype=np.float32)
        for i in range(self.num_bands):
            lo, hi = max(0, freq_bins[i]), max(freq_bins[i] + 1, freq_bins[i + 1])
            band_vals[i] = float(np.mean(fft[lo:hi])) if hi > lo else float(fft[lo])

        cur_peak = float(np.max(band_vals))
        self._peak_history = max(self._peak_history * _PEAK_DECAY, cur_peak, 0.05)
        normalized = np.clip(band_vals / self._peak_history, 0.0, 1.0)
        shaped = (normalized ** 1.30) * (self.intensity / 0.30)

        # High frequency attenuation
        weights = np.linspace(1.0, 0.60, self.num_bands, dtype=np.float32)
        shaped *= weights

        with self.lock:
            self._smooth_bands += _ALPHA * (shaped - self._smooth_bands)
            self._update_bars()

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
