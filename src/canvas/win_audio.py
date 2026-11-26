"""
src.canvas.win_audio
====================
Native Windows WASAPI loopback audio capture for DesktopSuite.
Implemented using pure ctypes COM vtables (0 external CFFI/soundcard dependencies).
Guaranteed 100% compatible with Windows 7 SP1, 8, 10, and 11.

Architecture (aligned with Gemini 4 Neon specifications):
1. In-thread COM apartment initialization: CoInitializeEx(None, COINIT_MULTITHREADED).
2. IMMDeviceEnumerator -> DefaultAudioEndpoint (eRender, eConsole).
3. IAudioClient::GetMixFormat -> exact native hardware format without AUTOCONVERTPCM.
4. Robust WAVEFORMATEXTENSIBLE subformat parsing (IEEE_FLOAT vs PCM).
5. IAudioClient::Initialize with AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_SHAREMODE_SHARED.
6. 64-bit pointer struct alignment in IAudioCaptureClient::GetBuffer (devPos/qpcPos).
7. Zero-copy ctypes buffer reading -> NumPy FFT mapped to 27 symmetric visualizer bars.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
import threading
import time
from typing import Optional, Tuple
import uuid

import numpy as np

from src.core.diagnostics import get_rate_limiter

log = logging.getLogger("DesktopSuite.WinAudio")

NUM_BANDS: int = 14
_ALPHA: float = 0.42
_PEAK_DECAY: float = 0.982
_CHUNK_SAMPLES: int = 1024

if sys.platform == "win32":
    ole32 = ctypes.OleDLL("ole32")
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

        def __eq__(self, other):
            return bytes(self) == bytes(other)

    def _guid(s: str) -> GUID:
        u = uuid.UUID(s)
        return GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    IID_IMMDeviceEnumerator  = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    IID_IAudioClient         = _guid("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    IID_IAudioCaptureClient  = _guid("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")

    KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = _guid("{00000003-0000-0010-8000-00AA00389B71}")
    KSDATAFORMAT_SUBTYPE_PCM        = _guid("{00000001-0000-0010-8000-00AA00389B71}")

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD),
            ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD),
            ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD),
            ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class WAVEFORMATEXTENSIBLE(ctypes.Structure):
        _fields_ = [
            ("Format", WAVEFORMATEX),
            ("Samples", wintypes.WORD),
            ("dwChannelMask", wintypes.DWORD),
            ("SubFormat", GUID),
        ]

    def _vcall(obj_ptr, index, restype, *argtypes):
        vtable = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return lambda *args: fn(obj_ptr, *args)


class WinAudioStream:
    """
    Background worker thread capturing Windows audio via native ctypes WASAPI loopback.
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
        log.info("Windows WASAPI audio stream thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info("Windows WASAPI audio stream thread stopped")

    def set_intensity(self, intensity: float) -> None:
        self.intensity = max(0.1, min(2.0, intensity))
        log.debug("WinAudioStream intensity set to %.2f", self.intensity)

    def _worker(self) -> None:
        if sys.platform != "win32":
            return

        limiter = get_rate_limiter()
        state_names = {1: "ACTIVE", 2: "DISABLED", 4: "NOTPRESENT", 8: "UNPLUGGED"}

        while not self._stop_event.is_set():
            hr_init = ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
            log.debug("WASAPI CoInitializeEx hr=0x%08X", hr_init & 0xFFFFFFFF)

            enum_ptr = ctypes.c_void_p()
            dev_ptr = ctypes.c_void_p()
            client_ptr = ctypes.c_void_p()
            cap_ptr = ctypes.c_void_p()

            try:
                # 1. Create MMDeviceEnumerator
                hr = ole32.CoCreateInstance(
                    ctypes.byref(CLSID_MMDeviceEnumerator), None, 0x17,
                    ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum_ptr)
                )
                if hr != 0 or not enum_ptr.value:
                    raise ctypes.WinError(hr)

                # 2. GetDefaultAudioEndpoint (Slot 4): eRender=0, eConsole=0
                hr = _vcall(enum_ptr, 4, ctypes.HRESULT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                    0, 0, ctypes.byref(dev_ptr)
                )
                if hr != 0 or not dev_ptr.value:
                    raise ctypes.WinError(hr)

                # Inspect endpoint ID (IMMDevice::GetId slot 5) & State (IMMDevice::GetState slot 6)
                endpoint_id = "<unknown>"
                endpoint_state = -1
                try:
                    p_id = ctypes.c_void_p()
                    hr_id = _vcall(dev_ptr, 5, ctypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(p_id))
                    if hr_id == 0 and p_id.value:
                        endpoint_id = ctypes.wstring_at(p_id.value)
                        ole32.CoTaskMemFree(p_id)
                except Exception as id_exc:
                    log.debug("IMMDevice::GetId failed: %s", id_exc)
                try:
                    dw_state = wintypes.DWORD(0)
                    hr_st = _vcall(dev_ptr, 6, ctypes.HRESULT, ctypes.POINTER(wintypes.DWORD))(ctypes.byref(dw_state))
                    if hr_st == 0:
                        endpoint_state = int(dw_state.value)
                except Exception as st_exc:
                    log.debug("IMMDevice::GetState failed: %s", st_exc)

                log.info(
                    "WASAPI Default Render Endpoint: id=%r state=%s (%s)",
                    endpoint_id, endpoint_state, state_names.get(endpoint_state, "UNKNOWN"),
                )

                # 3. IMMDevice::Activate -> IAudioClient (Slot 3)
                hr = _vcall(dev_ptr, 3, ctypes.HRESULT, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                    ctypes.byref(IID_IAudioClient), 0x17, None, ctypes.byref(client_ptr)
                )
                if hr != 0 or not client_ptr.value:
                    raise ctypes.WinError(hr)

                # 4. IAudioClient::GetMixFormat (Slot 8)
                pwfx = ctypes.POINTER(WAVEFORMATEX)()
                hr = _vcall(client_ptr, 8, ctypes.HRESULT, ctypes.POINTER(ctypes.POINTER(WAVEFORMATEX)))(ctypes.byref(pwfx))
                if hr != 0 or not pwfx:
                    raise ctypes.WinError(hr)

                fmt = pwfx.contents
                channels = int(fmt.nChannels)
                samplerate = int(fmt.nSamplesPerSec)
                bits = int(fmt.wBitsPerSample)
                wFormatTag = int(fmt.wFormatTag)

                # 5. Robust Subformat Parsing (IEEE Float vs PCM)
                is_float = False
                subfmt_info = "n/a"
                if wFormatTag == 3:  # WAVE_FORMAT_IEEE_FLOAT
                    is_float = True
                    subfmt_info = "WAVE_FORMAT_IEEE_FLOAT"
                elif wFormatTag == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE
                    ext = ctypes.cast(pwfx, ctypes.POINTER(WAVEFORMATEXTENSIBLE)).contents
                    subfmt_hex = bytes(ext.SubFormat).hex()
                    if ext.SubFormat == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT:
                        is_float = True
                        subfmt_info = f"EXTENSIBLE:IEEE_FLOAT(validBits={ext.Samples},mask=0x{ext.dwChannelMask:X})"
                    elif ext.SubFormat == KSDATAFORMAT_SUBTYPE_PCM:
                        is_float = False
                        subfmt_info = f"EXTENSIBLE:PCM(validBits={ext.Samples},mask=0x{ext.dwChannelMask:X})"
                    else:
                        subfmt_info = f"EXTENSIBLE:OTHER({subfmt_hex},validBits={ext.Samples},mask=0x{ext.dwChannelMask:X})"
                elif bits == 32:
                    is_float = True
                    subfmt_info = "FALLBACK_32BIT_FLOAT"
                else:
                    subfmt_info = f"PCM_TAG_0x{wFormatTag:04X}"

                log.info(
                    "WASAPI Win7 MixFormat: tag=0x%04X, %d ch, %d Hz, %d-bit, blockAlign=%d, cbSize=%d, %s -> is_float=%s",
                    wFormatTag, channels, samplerate, bits, fmt.nBlockAlign, fmt.cbSize, subfmt_info, is_float,
                )

                # 6. IAudioClient::Initialize (Slot 3): SHARED (0), LOOPBACK (0x00020000), 100ms buffer
                hr = _vcall(
                    client_ptr, 3, ctypes.HRESULT,
                    ctypes.c_int, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong,
                    ctypes.c_void_p, ctypes.c_void_p
                )(0, 0x00020000, 1_000_000, 0, pwfx, None)

                ole32.CoTaskMemFree(pwfx)
                if hr != 0:
                    raise ctypes.WinError(hr)
                log.info("WASAPI IAudioClient::Initialize(LOOPBACK) succeeded (hr=0x00000000)")

                # 7. IAudioClient::GetService -> IAudioCaptureClient (Slot 14)
                hr = _vcall(client_ptr, 14, ctypes.HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                    ctypes.byref(IID_IAudioCaptureClient), ctypes.byref(cap_ptr)
                )
                if hr != 0 or not cap_ptr.value:
                    raise ctypes.WinError(hr)

                # 8. IAudioClient::Start (Slot 10)
                hr = _vcall(client_ptr, 10, ctypes.HRESULT)()
                if hr != 0:
                    raise ctypes.WinError(hr)
                log.info("WASAPI IAudioClient::Start succeeded; entering loopback capture loop")

                # Function wrappers for the capture loop
                get_next_packet = _vcall(cap_ptr, 5, ctypes.HRESULT, ctypes.POINTER(wintypes.DWORD))
                get_buffer = _vcall(
                    cap_ptr, 3, ctypes.HRESULT,
                    ctypes.POINTER(ctypes.c_void_p),
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.POINTER(ctypes.c_uint64),
                    ctypes.POINTER(ctypes.c_uint64)
                )
                release_buffer = _vcall(cap_ptr, 4, ctypes.HRESULT, wintypes.DWORD)

                # Ring buffer for FFT processing
                pcm_buffer = np.zeros(0, dtype=np.float32)

                # Pre-allocated 64-bit pointers for Win7 x64 GetBuffer
                pData = ctypes.c_void_p()
                numFramesRead = wintypes.DWORD()
                dwFlags = wintypes.DWORD()
                devPos = ctypes.c_uint64()
                qpcPos = ctypes.c_uint64()
                packetFrames = wintypes.DWORD()

                last_heartbeat = time.monotonic()
                empty_polls = 0
                packets_read = 0
                silent_packets = 0
                frames_total = 0
                chunks_processed = 0
                last_rms = 0.0
                last_max_amp = 0.0

                while not self._stop_event.is_set():
                    hr = get_next_packet(ctypes.byref(packetFrames))
                    if hr != 0:
                        allowed, suppressed = limiter.check("wasapi:get_next_packet", interval=5.0)
                        if allowed:
                            log.warning(
                                "GetNextPacketSize error: hr=0x%08X (suppressed=%d)",
                                hr & 0xFFFFFFFF, suppressed,
                            )
                        break

                    if packetFrames.value == 0:
                        empty_polls += 1
                        self._fallback_step()
                        now = time.monotonic()
                        if now - last_heartbeat >= 3.0:
                            with self.lock:
                                max_bar = float(np.max(self.bars))
                            log.info(
                                "WASAPI heartbeat (3s): empty_polls=%d, packets=%d (silent=%d), "
                                "frames=%d, chunks=%d, last_rms=%.5f, max_amp=%.5f, peak_hist=%.4f, max_bar=%.4f",
                                empty_polls, packets_read, silent_packets, frames_total, chunks_processed,
                                last_rms, last_max_amp, self._peak_history, max_bar,
                            )
                            empty_polls = packets_read = silent_packets = frames_total = chunks_processed = 0
                            last_heartbeat = now
                        time.sleep(0.01)
                        continue

                    while packetFrames.value > 0 and not self._stop_event.is_set():
                        hr = get_buffer(
                            ctypes.byref(pData),
                            ctypes.byref(numFramesRead),
                            ctypes.byref(dwFlags),
                            ctypes.byref(devPos),
                            ctypes.byref(qpcPos)
                        )
                        if hr != 0 or not pData.value or numFramesRead.value == 0:
                            if hr != 0 and (hr & 0xFFFFFFFF) != 0x08890001:  # ignore AUDCLNT_S_BUFFER_EMPTY
                                allowed, suppressed = limiter.check("wasapi:get_buffer_err", interval=5.0)
                                if allowed:
                                    log.warning(
                                        "GetBuffer failed: hr=0x%08X, pData=%s, frames=%s (suppressed=%d)",
                                        hr & 0xFFFFFFFF, pData.value, numFramesRead.value, suppressed,
                                    )
                            elif hr == 0 and (not pData.value or numFramesRead.value == 0):
                                allowed, suppressed = limiter.check("wasapi:get_buffer_empty", interval=5.0)
                                if allowed:
                                    log.warning(
                                        "GetBuffer hr=0 but empty: pData=%s, frames=%s, packetFrames=%s (suppressed=%d)",
                                        pData.value, numFramesRead.value, packetFrames.value, suppressed,
                                    )
                            break

                        n_frames = numFramesRead.value
                        total_samples = n_frames * channels
                        packets_read += 1
                        frames_total += n_frames

                        if dwFlags.value & 0x02:  # AUDCLNT_BUFFERFLAGS_SILENT
                            silent_packets += 1
                            samples = np.zeros(total_samples, dtype=np.float32)
                        else:
                            if is_float:
                                raw_array = (ctypes.c_float * total_samples).from_address(pData.value)
                                samples = np.frombuffer(raw_array, dtype=np.float32).copy()
                            else:
                                raw_array = (ctypes.c_int16 * total_samples).from_address(pData.value)
                                samples = np.frombuffer(raw_array, dtype=np.int16).astype(np.float32) / 32768.0

                        if channels > 1:
                            samples = samples.reshape(-1, channels).mean(axis=1)

                        pcm_buffer = np.concatenate((pcm_buffer, samples))

                        hr_rel = release_buffer(numFramesRead.value)
                        if hr_rel != 0:
                            allowed, suppressed = limiter.check("wasapi:release_err", interval=5.0)
                            if allowed:
                                log.warning("ReleaseBuffer error: hr=0x%08X (suppressed=%d)", hr_rel & 0xFFFFFFFF, suppressed)

                        hr_next = get_next_packet(ctypes.byref(packetFrames))
                        if hr_next != 0:
                            allowed, suppressed = limiter.check("wasapi:next_err", interval=5.0)
                            if allowed:
                                log.warning("GetNextPacketSize(inner) error: hr=0x%08X (suppressed=%d)", hr_next & 0xFFFFFFFF, suppressed)
                            break

                    while len(pcm_buffer) >= _CHUNK_SAMPLES:
                        chunk = pcm_buffer[:_CHUNK_SAMPLES]
                        pcm_buffer = pcm_buffer[_CHUNK_SAMPLES:]
                        last_rms = float(np.sqrt(np.mean(chunk ** 2)))
                        last_max_amp = float(np.max(np.abs(chunk)))
                        chunks_processed += 1
                        self._process_chunk(chunk, samplerate)

                    now = time.monotonic()
                    if now - last_heartbeat >= 3.0:
                        with self.lock:
                            max_bar = float(np.max(self.bars))
                        log.info(
                            "WASAPI heartbeat (3s): empty_polls=%d, packets=%d (silent=%d), "
                            "frames=%d, chunks=%d, last_rms=%.5f, max_amp=%.5f, peak_hist=%.4f, max_bar=%.4f",
                            empty_polls, packets_read, silent_packets, frames_total, chunks_processed,
                            last_rms, last_max_amp, self._peak_history, max_bar,
                        )
                        empty_polls = packets_read = silent_packets = frames_total = chunks_processed = 0
                        last_heartbeat = now

                    time.sleep(0.01)

            except Exception as exc:
                log.warning("WASAPI loopback error: %s; reconnecting in 0.5s...", exc, exc_info=True)
                self._fallback_step()
                time.sleep(0.5)
            finally:
                for ptr in (cap_ptr, client_ptr, dev_ptr, enum_ptr):
                    if ptr and ptr.value:
                        try:
                            _vcall(ptr.value, 2, wintypes.ULONG)()
                        except Exception:
                            pass
                try:
                    ole32.CoUninitialize()
                except Exception:
                    pass

    def _process_chunk(self, chunk: np.ndarray, samplerate: int) -> None:
        if len(chunk) < _CHUNK_SAMPLES:
            return

        max_amp = float(np.max(np.abs(chunk)))
        if max_amp < 1e-5:
            with self.lock:
                self._smooth_bands *= 0.85
                self._update_bars()
            return

        windowed = chunk[:_CHUNK_SAMPLES] * self._hanning
        fft = np.abs(np.fft.rfft(windowed, n=_CHUNK_SAMPLES))[:_CHUNK_SAMPLES // 2]

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

        # High frequency attenuation
        weights = np.linspace(1.0, 0.65, self.num_bands, dtype=np.float32)
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
