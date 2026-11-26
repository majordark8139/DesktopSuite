# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

proj_root = Path.cwd()

datas = [
    ('assets/fonts', 'assets/fonts'),
    ('assets/icons', 'assets/icons'),
]

# Include bundled binaries (e.g. Windows 7 API path DLL and mpv)
binaries = []
dll_path = proj_root / 'assets' / 'bin' / 'api-ms-win-core-path-l1-1-0.dll'
if dll_path.exists():
    binaries.append((str(dll_path), '.'))

if (proj_root / 'assets' / 'bin').exists():
    datas.append(('assets/bin', 'assets/bin'))

a = Analysis(
    ['src/main.py'],
    pathex=[str(proj_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'numpy',
        'cairo',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
        'src.core.diagnostics',
        'src.core.win7_font_engine',
        'src.core.win7_single_instance',
        'src.wallpaper.win_engine',
        'src.canvas.win_window',
        'src.canvas.win_audio',
        'src.windows.app',
        'src.windows.control_center',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'gi',
        'gi.repository',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DesktopSuite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/desktop-suite.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DesktopSuite',
)
