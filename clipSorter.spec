# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# --- Dynamic Path Resolution ---
import os
import sys

# Get the directory where the .spec file is located
spec_root = os.path.dirname(os.path.abspath(sys.argv[0]))

# --- External Dependencies and Data ---
yolo_model_path = os.path.join(spec_root, 'yolov8n.pt')
if not os.path.exists(yolo_model_path):
    # This should be handled gracefully, perhaps by downloading or raising a specific error
    # For now, we'll raise an error to prevent silent failures
    raise FileNotFoundError(f"YOLO model not found at: {yolo_model_path}")

_bundle_ffmpeg = os.environ.get("BUNDLE_FFMPEG", "0") == "1" # "1" to bundle, "0" to expect on PATH

_bin_ext = ".exe" if sys.platform == "win32" else ""

common_datas = [
    (yolo_model_path, '.'),
    (os.path.join(spec_root, 'src'), 'src'),
]

common_binaries = []
if _bundle_ffmpeg:
    ffmpeg_exe_path = os.path.join(spec_root, 'scripts', 'dist', 'bin', f'ffmpeg{_bin_ext}')
    ffprobe_exe_path = os.path.join(spec_root, 'scripts', 'dist', 'bin', f'ffprobe{_bin_ext}')
    
    # We won't raise error here for BUNDLE_FFMPEG=0
    if os.path.exists(ffmpeg_exe_path) and os.path.exists(ffprobe_exe_path):
        common_binaries = [
            (ffmpeg_exe_path, '.'),
            (ffprobe_exe_path, '.'),
        ]

# --- Hidden Imports ---
# Explicitly include commonly missed or dynamically imported modules
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
    pathex=[spec_root], # Only root
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
    console=True, # Windowed mode with console for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- CLI Tool ---
a_cli = Analysis(
    ['sort.py'], 
    pathex=[spec_root], # Only root
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
    console=True, # Console mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
