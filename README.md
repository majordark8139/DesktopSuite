# DesktopSuite

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20(X11)-orange.svg)]()
[![GTK: 3.0](https://img.shields.io/badge/GTK-3.0-green.svg)]()

> **DesktopSuite** is an elegant, modular Desktop Widget & Live Wallpaper Engine for Linux. Featuring 26 iconic community-inspired Rainmeter themes, independent component drag-and-scale mechanics, decoupled RGB color customizers, real-time audio visualization, and a seamless video wallpaper engine.

---

## ✨ Features

- **26 Master Community Themes**: From minimal typography to sci-fi cyberdecks, retrogaming pixel art, and mid-century functionalism:
  - *Mond Minimal*, *Cyberpunk 2077*, *FLHUD*, *Enigma Classic*, *Pixel Arcade*, *Liquid Glass*, *Circular Orbit*, *Textime*, *Braun Dieter*, *Nordic Glint*, *Matrix CLI*, *Zen Garden*, *Vector Tactical*, and more.
- **Decoupled Component Architecture**:
  - Clock, Date, and Visualizer can each be individually toggled, positioned, dragged, and anchored anywhere on screen.
  - **Independent Component Scaling**: Adjust `Clock Scale`, `Date Scale`, and `Visualizer Scale` separately or link them to a master canvas scale.
  - **Decoupled Color Customization**: Separate native color pickers for Clock, Date, and Audio Visualizer with live instant canvas redraw.
- **Dynamic Cairo Canvas**:
  - Multi-threaded rendering pipeline with double-buffered transparency and subpixel Fontconfig font matching.
  - X11 desktop click pass-through and automatic background focus management for seamless daily desktop use.
- **Live Video Wallpaper Engine**:
  - Embedded borderless MPV video renderer mapped directly to your desktop background.
  - Multi-monitor resolution awareness with zero desktop window interference.
  - Instant toggle via CLI hotkey (`desktop-suite --toggle-wallpaper`) and built-in XFCE keyboard shortcut binder (`<Super>w`).
- **Real-Time Audio Spectrum**:
  - Smooth audio visualizer with CAVA/PulseAudio backend, customizable bar counts, spectrum heights, and intensity multipliers.

---

## 📸 Master Theme Collection (26 Themes)

| Theme Name | Style Description | Primary Typography |
| :--- | :--- | :--- |
| **Mond Minimal** | Community favorite with tracked day, dashed time subtext, and baseline bars | Anurati & Montserrat |
| **Cyberpunk 2077** | Chromatic aberration cyan/magenta glow, chamfered status badge, and neon bars | Orbitron Bold |
| **FLHUD** | Sci-fi bracketed HUD digits `[ 04:20 ]`, dual-column subtext, flanked bars | Orbitron & Share Tech Mono |
| **Enigma Classic** | Classic HUD layout with LOCAL header, dotted date notation, precision bars | Share Tech Mono |
| **Pixel Arcade** | 8-bit retro gaming numerals with stepped LED matrix block visualizer | Press Start 2P |
| **Liquid Glass** | Translucent frosted glass card with linear specular border highlights | Montserrat Bold |
| **Circular Orbit** | Concentric circular dial with orbital second satellite and radial ray visualizer | Montserrat Bold |
| **Textime** | Phonetic word clock ("FOUR" / "TWENTY") with micro tracked date | Montserrat Bold & Light |
| **Braun Dieter** | Mid-century German functionalism with signature safety-orange separator dot | Montserrat Bold |
| **Nordic Glint** | Refined classical roman serif layout with diamond glyph separators (`◇`) | Cinzel |
| **Matrix CLI** | Monospace green phosphor terminal prompt `[user@mint ~]$` with ASCII meter | Share Tech Mono |
| **Zen Garden** | Serene circular proportions flanked by pebble rings and water ripple waves | Comfortaa |
| **Vector Tactical** | Military HUD stencil digits flanked by crosshairs and targeting reticles | Orbitron |
| **Elegance Two-Tone** | Ultra-tall hairline condensed numerals with decoupled hour/minute weights | Bebas Neue |
| **Elegance 2** | Hairline ultra-thin geometric numerals with extra-wide tracked subtext | Montserrat Light |
| **Lumiero Capsule** | Clean numerals with frosted rounded pill date badge and symmetrical bars | Bebas Neue & Montserrat |
| **Lines 2.0** | Numerals with twin baseline rules extending across screen and hairline bars | Montserrat Bold |
| **Dot Matrix LED** | Digital vacuum fluorescent VFD style with fading dot matrix columns | VT323 |
| **Astro Editorial** | Poster-scale stacked numerals with vertical day text and solid wave visualizer | Bebas Neue |
| **Neumorph Soft** | Soft UI embossed dual light/shadow styling with recessed pill container | Montserrat Bold |
| **Sonder Axis** | Vertical Japanese accent spine with Shojumaru day header and dual-direction bars | Shojumaru & Montserrat |
| **Wild Youth** | Expressive authentic handwriting with soft drop shadow and gradient bars | Caveat & Wild Youth |
| **Chrono Block** | Condensed numerals with square colon blocks and LED visualizer | Bebas Neue & SF Sports Night |
| **Vertical Overlap**| Massive architectural numbers tightly stacked with watermark day | Anton |
| **Mond Clean** | Minimalist clean white-on-transparent reference clock | Montserrat Bold |
| **Original Cursive**| Flowing calligraphic cursive script with smooth baseline visualizer | Caveat |

---

## 🚀 Quick Start & Installation

### 1. Prerequisites (Ubuntu / Debian / Linux Mint)
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi python3-gi-cairo \
                    gir1.2-gtk-3.0 mpv libfontconfig1 fontconfig
```

### 2. Install DesktopSuite
Clone the repository and run the installer:
```bash
git clone https://github.com/your-username/DesktopSuite.git
cd DesktopSuite
./install.sh
```

The installer will:
1. Create the executable launcher at `~/.local/bin/desktop-suite`.
2. Install bundled fonts to `~/.local/share/fonts/desktop-suite/` and refresh Fontconfig.
3. Install the application icon to `~/.local/share/icons/hicolor/256x256/apps/`.
4. Register the desktop application menu entry `desktop-suite.desktop`.

---

## 🎮 Usage

### GUI Control Center
Launch from your application menu or run from terminal:
```bash
desktop-suite
```

- **Live Wallpaper Tab**: Browse video wallpapers, select monitors, toggle live playback, and bind XFCE shortcuts (`<Super>w`).
- **Clock & Canvas Tab**: Select from 26 themes, customize master & independent component scales, pick decoupled component colors, and toggle edit/drag mode.
- **Audio Visualizer Tab**: Tune bar counts, sensitivity, smoothing factor, and visualizer intensity.

### Edit / Drag Mode
Click **"Toggle Edit Mode"** in the GUI or press your configured edit shortcut to display interactive drag bounding boxes around Clock, Date, and Visualizer. Drag them anywhere on your desktop and release to save coordinates.

### Command-Line Interface (CLI)
DesktopSuite includes lightweight CLI control flags for keybindings and scripts:
```bash
desktop-suite                      # Launch full GTK3 Settings GUI & Engine
desktop-suite --daemon             # Launch background widget canvas & audio service
desktop-suite --toggle-wallpaper   # Toggle live video wallpaper on/off instantly
desktop-suite --kill-wallpaper     # Terminate any running live wallpaper process
desktop-suite --version            # Print version information
```

---

## 🧪 Testing

Run the automated headless Cairo verification suite to test all 26 themes:
```bash
python3 -m unittest discover tests
```

---

## 🗑️ Uninstallation

To cleanly remove DesktopSuite integration from your user environment:
```bash
./uninstall.sh
```
*(Your git repository and configuration files remain untouched)*

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
