# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

proj_root = Path.cwd()

datas = [
    ('assets/fonts', 'assets/fonts'),
    ('assets/icons', 'assets/icons'),
]

# Include bundled mpv if present
if (proj_root / 'assets' / 'bin').exists():
    datas.append(('assets/bin', 'assets/bin'))

a = Analysis(
    ['src/main.py'],
    pathex=[str(proj_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'numpy',
        'cairo',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'soundcard',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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
