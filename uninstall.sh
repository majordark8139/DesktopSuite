#!/usr/bin/env bash
set -e

echo "=== Uninstalling DesktopSuite ==="

BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
FONTS_DIR="${HOME}/.local/share/fonts/desktop-suite"

# 1. Remove launcher
if [ -f "${BIN_DIR}/desktop-suite" ]; then
    echo "Removing launcher: ${BIN_DIR}/desktop-suite"
    rm -f "${BIN_DIR}/desktop-suite"
fi

# 2. Remove desktop entry
if [ -f "${APPS_DIR}/desktop-suite.desktop" ]; then
    echo "Removing desktop entry: ${APPS_DIR}/desktop-suite.desktop"
    rm -f "${APPS_DIR}/desktop-suite.desktop"
fi

# 3. Remove application icon
if [ -f "${ICONS_DIR}/desktop-suite.png" ]; then
    echo "Removing application icon: ${ICONS_DIR}/desktop-suite.png"
    rm -f "${ICONS_DIR}/desktop-suite.png"
fi

# 4. Remove installed fonts
if [ -d "${FONTS_DIR}" ]; then
    echo "Removing fonts: ${FONTS_DIR}"
    rm -rf "${FONTS_DIR}"
    if command -v fc-cache >/dev/null 2>&1; then
        echo "Updating font cache..."
        fc-cache -f "${HOME}/.local/share/fonts" 2>/dev/null || true
    fi
fi

# 5. Refresh databases
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "=== DesktopSuite uninstalled successfully! ==="
echo "(Repository files remained untouched)"
