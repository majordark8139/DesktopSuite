# DesktopSuite for Windows (Windows 7 / 8 / 10 / 11)

Native, hardware-accelerated desktop widget and live wallpaper engine for Windows, ported with 100% theme preservation and low-resource efficiency.

---

## 🌟 Highlights & Windows Architecture

1. **Live Video Wallpaper via WorkerW**:
   - Embeds `mpv` directly into Windows Explorer's desktop background using the `WorkerW` / `Progman` message (`0x052C`) trick.
   - Unlike Linux XFCE, **your desktop icons remain 100% visible and interactive on top of the live wallpaper**.
   - Hardware-accelerated decoding using DirectX / DXVA2 (`--vo=gpu --hwdec=dxva2-copy`) on Intel HD Graphics (Haswell i3 HD 4400) and dedicated GPUs for near 0% CPU consumption.

2. **Native Win32 Layered HUD Canvas**:
   - All 26 vector Cairo themes run natively with per-pixel alpha transparency via `UpdateLayeredWindow`.
   - Normal mode is click-through (`WS_EX_TRANSPARENT`), allowing interaction with icons and apps underneath.
   - Edit mode enables interactive drag-and-drop bounding box repositioning with atomic persistence.

3. **WASAPI Loopback Audio Visualizer**:
   - Captures real-time system audio (Spotify, YouTube, media players, games) via native Windows WASAPI loopback without requiring virtual audio cables.
   - 27-bar symmetric spectrum with logarithmic frequency binning and Hanning window FFT math.

4. **PyQt5 Control Center GUI**:
   - Full dark Catppuccin-styled settings studio with decoupled RGB color pickers, volume/speed tuning, and theme selectors.

---

## 🚀 Quick Start on Windows

### Option 1: Standalone Portable Binary (Recommended)
1. Download `DesktopSuite-Windows-Portable.zip` from [GitHub Actions Builds](https://github.com/majordark8139/DesktopSuite/actions) or Releases.
2. Extract the archive anywhere on your machine.
3. Run `DesktopSuite.exe` (or `Launch_DesktopSuite.bat` for automatic first-launch dependency resolution).

> [!NOTE]
> **Windows 7 Out-of-the-Box Compatibility:**
> The distribution bundles `api-ms-win-core-path-l1-1-0.dll` both in the portable root and inside the executable bundle, resolving the missing Python 3.10 DLL error on Windows 7 SP1 automatically. If Visual C++ runtimes are missing on an unpatched Windows 7 installation, running `Launch_DesktopSuite.bat` will automatically download and install them silently on first run.

### Option 2: Running from Source (Python 3.8 - 3.12)
1. Install Python 3.8+ (for Windows 7, use Python 3.8.10 or `cpython-win7`).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install `mpv` (e.g. via Chocolatey `choco install mpv`, or place `mpv.exe` in `assets/bin/mpv.exe`).
4. Launch DesktopSuite:
   ```bash
   python src/main.py
   ```

---

## 🎮 Command-Line Flags on Windows

```powershell
python src/main.py                      # Open full Control Center & start engines
python src/main.py --daemon             # Launch background canvas & wallpaper silently
python src/main.py --toggle-wallpaper   # Toggle wallpaper playback on/off (bindable to hotkeys)
python src/main.py --kill-wallpaper     # Terminate wallpaper process
```

---

## 🖥️ Compatibility
- **Operating Systems:** Windows 7 SP1 (with Aero), Windows 8.1, Windows 10, Windows 11.
- **Hardware Verified:** Tested on dual-core Haswell Intel Core i3-4005U with Intel HD 4400 and 4 GB RAM.
