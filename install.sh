#!/usr/bin/env bash
set -e

# Resolve absolute path to project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing DesktopSuite ==="
echo "Project Directory: ${PROJECT_DIR}"

# 1. Ensure user directories exist
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
FONTS_DIR="${HOME}/.local/share/fonts/desktop-suite"

mkdir -p "${BIN_DIR}" "${APPS_DIR}" "${ICONS_DIR}" "${FONTS_DIR}"

# 2. Create launcher wrapper in ~/.local/bin/desktop-suite
LAUNCHER="${BIN_DIR}/desktop-suite"
echo "[1/5] Creating launcher wrapper at ${LAUNCHER}..."
cat <<EOF > "${LAUNCHER}"
#!/usr/bin/env bash
exec python3 "${PROJECT_DIR}/src/main.py" "\$@"
EOF
chmod +x "${LAUNCHER}"

# 3. Install application icon
echo "[2/5] Installing application icon to ${ICONS_DIR}/desktop-suite.png..."
cp "${PROJECT_DIR}/assets/icons/desktop-suite.png" "${ICONS_DIR}/desktop-suite.png"

# 4. Install bundled fonts to user fonts directory
echo "[3/5] Installing bundled fonts to ${FONTS_DIR}..."
cp "${PROJECT_DIR}/assets/fonts/"*.* "${FONTS_DIR}/" 2>/dev/null || true
if command -v fc-cache >/dev/null 2>&1; then
    echo "Updating font cache..."
    fc-cache -f "${FONTS_DIR}"
fi

# 5. Create desktop menu entry
DESKTOP_FILE="${APPS_DIR}/desktop-suite.desktop"
echo "[4/5] Generating desktop entry at ${DESKTOP_FILE}..."
cat <<EOF > "${DESKTOP_FILE}"
[Desktop Entry]
Version=1.0
Type=Application
Name=DesktopSuite
GenericName=Desktop Widget & Wallpaper Engine
Comment=Elegant Desktop Widget & Live Wallpaper Engine for Linux
Exec=${LAUNCHER}
Icon=desktop-suite
Terminal=false
Categories=Utility;DesktopSettings;GTK;
StartupNotify=true
Keywords=desktop;wallpaper;clock;visualizer;rainmeter;widgets;
EOF
chmod +x "${DESKTOP_FILE}"

# 6. Update desktop and icon databases
echo "[5/5] Updating desktop and icon databases..."
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "=== DesktopSuite installed successfully! ==="
echo "Launch from your application menu or run: desktop-suite"
