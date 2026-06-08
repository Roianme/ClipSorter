# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Paths to external dependencies (not directly used in Analysis, but serves as reference)
# These will be dynamically included based on BUNDLE_FFMPEG flag

# Common data and binaries to bundle
import os
import sys

yolo_model = 'yolov8n.pt'
_bundle_ffmpeg = os.environ.get("BUNDLE_FFMPEG", "1") == "1"
_bin_ext = ".exe" if sys.platform == "win32" else ""

common_datas = [
    (yolo_model, '.'),
]

common_binaries = []
if _bundle_ffmpeg:
    common_binaries = [
        (f'scripts/dist/bin/ffmpeg{_bin_ext}', '.'),
        (f'scripts/dist/bin/ffprobe{_bin_ext}', '.'),
    ]

# GUI Application
a_gui = Analysis(
    ['app.py'], # Note: app.py is in root
    pathex=['F:\pili', 'F:\pili\src'],
    binaries=common_binaries,
    datas=common_datas,
    hiddenimports=['tkinterdnd2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    [],
    name='ClipSorter-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# CLI Tool
a_cli = Analysis(
    ['sort.py'], # Note: sort.py is in root, which calls cli.main()
    pathex=['F:\pili', 'F:\pili\src'],
    binaries=common_binaries,
    datas=common_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    [],
    name='ClipSorter-CLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True, # Console mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
