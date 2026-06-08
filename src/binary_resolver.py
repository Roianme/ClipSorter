# src/binary_resolver.py
"""
Priority chain for resolving ffmpeg/ffprobe paths:
  1. Environment variable override (for CI, Docker, power users)
  2. Bundled binary alongside the executable (thin-bundle mode)
  3. System PATH (for users who have FFmpeg installed natively)
Raises FileNotFoundError with a clear, actionable message if not found.
"""
import shutil
import sys
import os

FFMPEG_ENV_KEY = "CLIPSORTER_FFMPEG_PATH"
FFPROBE_ENV_KEY = "CLIPSORTER_FFPROBE_PATH"

_cache: dict[str, str] = {}


def resolve_binary(name: str) -> str:
    """Return the absolute path to 'ffmpeg' or 'ffprobe'."""
    if name in _cache:
        return _cache[name]

    env_key = FFMPEG_ENV_KEY if name == "ffmpeg" else FFPROBE_ENV_KEY

    # Priority 1: Explicit env override
    env_path = os.environ.get(env_key)
    if env_path and os.path.isfile(env_path):
        _cache[name] = env_path
        return env_path

    # Priority 2: Bundled next to executable (PyInstaller extracts to _MEIPASS)
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    suffix = ".exe" if sys.platform == "win32" else ""
    # Look for bundled binaries in the same directory as the executable,
    # or one level up if the script is in 'src' and executable in 'dist'
    bundled_path = os.path.join(base_dir, name + suffix)
    if not os.path.isfile(bundled_path) and 'src' in base_dir:
        # If running from src in dev mode or bundled structure is different
        bundled_path = os.path.join(os.path.dirname(base_dir), name + suffix)

    if os.path.isfile(bundled_path):
        _cache[name] = bundled_path
        return bundled_path


    # Priority 3: System PATH
    system_path = shutil.which(name)
    if system_path:
        _cache[name] = system_path
        return system_path

    raise FileNotFoundError(
        f"""'{name}' was not found on this system.
  Option 1: Install FFmpeg from https://ffmpeg.org/download.html
  Option 2: Set the environment variable {env_key} to the full path of {name}."""
    )


def check_all_dependencies() -> list[str]:
    """Returns a list of binary names that are missing. Empty list = all OK."""
    missing = []
    for binary in ["ffmpeg", "ffprobe"]:
        try:
            resolve_binary(binary)
        except FileNotFoundError:
            missing.append(binary)
    return missing
