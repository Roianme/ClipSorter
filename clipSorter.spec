# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# --- Dynamic Path Resolution ---
import os
import sys

# Get the directory where the .spec file is located
spec_root = os.path.dirname(os.path.abspath(sys.argv[0]))

# --- External Dependencies and Data ---
yolo_model_path = os.path.join(spec_root, 'yolov8n.pt')
# We do not raise error here as testing might not require subject detection
# if not os.path.exists(yolo_model_path):
#    raise FileNotFoundError(f"YOLO model not found at: {yolo_model_path}")

_bundle_ffmpeg = os.environ.get("BUNDLE_FFMPEG", "0") == "1"

# Determine platform specifics
if sys.platform == 'win32':
    ffmpeg_bin = 'ffmpeg.exe'
    ffprobe_bin = 'ffprobe.exe'
elif sys.platform == 'darwin':
    ffmpeg_bin = 'ffmpeg'
    ffprobe_bin = 'ffprobe'
else:
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")

ffmpeg_src = os.path.join(spec_root, 'scripts', 'dist', 'bin', ffmpeg_bin)
ffprobe_src = os.path.join(spec_root, 'scripts', 'dist', 'bin', ffprobe_bin)

common_datas = [
    (yolo_model_path, '.'),
]

common_binaries = []
if _bundle_ffmpeg:
    if os.path.exists(ffmpeg_src) and os.path.exists(ffprobe_src):
        common_binaries = [
            (ffmpeg_src, ffmpeg_bin),
            (ffprobe_src, ffprobe_bin),
        ]
    else:
        print(f"WARNING: FFmpeg binaries not found at {ffmpeg_src} or {ffprobe_src}. Not bundling.")

# --- Hidden Imports ---
hidden_imports_common = [
    'tkinterdnd2', 
    'src.binary_resolver',
    'src.classifier', 
    'src.config_loader',
    'src.converter',
    'src.duplicate',
    'src.gui_utils',
    'src.mover',
    'src.pipeline',
    'src.pipeline_shared',
    'src.qc_audio',
    'src.qc_photo',
    'src.qc_video',
    'src.reporter',
    'src.scanner',
    'src.service',
    'src.sort_audio',
    'src.sort_photo',
    'src.sort_video',
    'src.version',
    'src.welcome_view',
    'torch',
    'ultralytics',
    'cv2',
    'numpy',
    'numba',
    'scipy',
    'rawpy',
    'PIL',
    'magic',
]

# --- GUI Application ---
a_gui = Analysis(
    ['app.py'], 
    pathex=[spec_root], 
    binaries=common_binaries,
    datas=common_datas,
    hiddenimports=hidden_imports_common,
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Mac BUNDLE
if sys.platform == 'darwin':
    app = BUNDLE(exe_gui,
                 name='ClipSorter.app',
                 icon=None,
                 bundle_identifier=None)

# CLI Tool
a_cli = Analysis(
    ['sort.py'], 
    pathex=[spec_root], 
    binaries=common_binaries,
    datas=common_datas,
    hiddenimports=hidden_imports_common,
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
    console=True, 
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
