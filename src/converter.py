"""Convert scanned media files to canonical formats in a temp work directory."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import io
import re
from pathlib import Path
from typing import Any, NotRequired, TypedDict, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
import threading

import numpy as np
from src.scanner import FileRecord
from src import pipeline_shared as ps
from src.binary_resolver import resolve_binary 

logger = logging.getLogger(__name__)

RAW_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".arw",
        ".cr2",
        ".cr3",
        ".nef",
        ".orf",
        ".raf",
        ".dng",
        ".rw2",
    }
)

CANONICAL_EXTENSIONS: dict[str, frozenset[str]] = {
    "video": frozenset({".mp4"}),
    "photo": frozenset({".jpg", ".jpeg"}),
    "audio": frozenset({".mp3"}),
}

WORK_DIR_NAME = "clipsorter_work"

SubProgressCallback = Callable[[float], None]


class ConvertedFileRecord(FileRecord, total=False):
    converted_path: NotRequired[str]
    skipped: NotRequired[bool]
    image_array: NotRequired[np.ndarray]  # In-memory image for RAW previews


def get_work_dir() -> Path:
    r"""Cross-platform temp work directory (e.g. %TEMP%\clipsorter_work on Windows)."""
    work_dir = Path(tempfile.gettempdir()) / WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _canonical_extension(detected_type: str) -> str:
    if detected_type == "video":
        return ".mp4"
    if detected_type == "audio":
        return ".mp3"
    return ".jpg"


def _is_canonical(record: FileRecord) -> bool:
    """
    Check if a file is already in a canonical extension.
    For videos, we return False to force a deeper check of codec and resolution.
    """
    if record["detected_type"] == "video":
        return False
    extension = record["extension"].lower()
    return extension in CANONICAL_EXTENSIONS[record["detected_type"]]


def _allocate_output_path(work_dir: Path, source: Path, suffix: str) -> Path:
    candidate = work_dir / f"{source.stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = work_dir / f"{source.stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _run_command(cmd: list[str], cancel_token: Optional[ps.CancellationToken] = None) -> subprocess.CompletedProcess[str]:
    ps.check_cancelled(cancel_token)
    kwargs = {"capture_output": True, "text": True, "check": False}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def _ffmpeg_available() -> bool:
    try:
        resolve_binary("ffmpeg")
        return True
    except FileNotFoundError:
        return False


def _ffprobe_available() -> bool:
    try:
        resolve_binary("ffprobe")
        return True
    except FileNotFoundError:
        return False


def _video_codec_name(source: Path) -> str | None:
    if not _ffprobe_available():
        return None

    cmd = [
        resolve_binary("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    result = _run_command(cmd)
    if result.returncode != 0:
        logger.warning(
            "ffprobe could not read video codec for %s: %s",
            source,
            result.stderr.strip() or result.stdout.strip(),
        )
        return None

    codec = result.stdout.strip().lower()
    return codec or None


def _is_h264(codec: str | None) -> bool:
    return codec in {"h264", "avc1"}


def _video_resolution(source: Path) -> tuple[int, int] | None:
    """Get (width, height) of video using ffprobe."""
    if not _ffprobe_available():
        return None

    cmd = [
        resolve_binary("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        str(source),
    ]
    result = _run_command(cmd)
    if result.returncode != 0:
        return None

    try:
        parts = result.stdout.strip().split("x")
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        pass
    return None


def _log_ffmpeg_failure(source: Path, result: subprocess.CompletedProcess[str]) -> None:
    detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
    logger.error("FFmpeg failed for %s: %s", source, detail)


def _convert_video(
    source: Path, 
    dest: Path, 
    config: dict[str, Any],
    sub_progress: SubProgressCallback | None = None,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> bool:
    if not _ffmpeg_available():
        logger.error("ffmpeg not found in PATH; cannot convert %s", source)
        return False

    codec = _video_codec_name(source)
    res = _video_resolution(source)
    standardize = config.get("video_standardize_1080p", False)

    if standardize and res is None:
        logger.warning(
            "Could not read resolution for %s; "
            "skipping rescale even though standardize=True",
            source.name,
        )

    logger.info("Converting video %s: codec=%s, resolution=%s, standardize=%s", 
                source.name, codec, res, standardize)

    # Determine if we actually need to rescale
    needs_rescale = False
    if standardize and res:
        # If height is not 1080, we need to rescale
        if res[1] != 1080:
            needs_rescale = True

    # If already H.264 and no standardization/rescale needed, just copy
    if _is_h264(codec) and not needs_rescale:
        logger.info("Video %s is already H.264 and 1080p-compliant; copying.", source.name)
        cmd = [resolve_binary("ffmpeg"), "-y", "-i", str(source), "-c", "copy", str(dest)]
        result = _run_command(cmd, cancel_token=cancel_token)
    else:
        logger.info("Transcoding video %s (codec=%s, rescale=%s)", source.name, codec, needs_rescale)
        # Transcode (needed for format change or resizing)
        cmd = [
            resolve_binary("ffmpeg"),
            "-y",
            "-i",
            str(source),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v",
            str(config["video_output_codec"]),
            "-crf",
            str(config["video_output_crf"]),
            "-preset", "faster",
            "-pix_fmt", "yuv420p",  # Essential for broad compatibility (Windows Media Player, etc.)
            "-c:a", "aac",
            "-b:a", "128k",
        ]

        if needs_rescale:
            # Scale to 1080p while maintaining aspect ratio, 
            # ensuring width is divisible by 2 for the encoder.
            cmd.extend(["-vf", "scale=-2:1080"])

        cmd.append(str(dest))
        
        if sub_progress:
            result = _run_ffmpeg_with_progress(cmd, source, sub_progress, cancel_token=cancel_token)
        else:
            result = _run_command(cmd, cancel_token=cancel_token)

    if result.returncode != 0:
        _log_ffmpeg_failure(source, result)
        return False

    return dest.is_file()


def _run_ffmpeg_with_progress(
    cmd: list[str], 
    source: Path, 
    callback: SubProgressCallback,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg and parse its output for progress (time=...)."""
    # Import locally to avoid potential circular dependency issues
    from src.qc_video import _run_ffprobe_duration_seconds # Corrected import for qc_video
    duration = _run_ffprobe_duration_seconds(source)
    
    if not duration:
        return _run_command(cmd)

    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "universal_newlines": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(cmd, **kwargs)

    full_output = []
    time_re = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

    try:
        while True:
            # Check for cancellation
            if cancel_token and cancel_token.is_cancelled():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise ps.PipelineCancelledError()

            # Read with timeout to allow cancellation check even if no output
            # However, readline() is blocking. We can use a small trick or just rely on output frequency.
            # Most ffmpeg transcoding produces output frequently.
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                full_output.append(line)
                match = time_re.search(line)
                if match:
                    h, m, s, _ms = map(int, match.groups())
                    elapsed = h * 3600 + m * 60 + s
                    progress_val = min(1.0, elapsed / duration)
                    callback(progress_val)
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=process.returncode,
        stdout="".join(full_output),
        stderr="",  # stderr merged into stdout via stderr=STDOUT in Popen
    )


def _convert_audio(
    source: Path, 
    dest: Path, 
    config: dict[str, Any],
    cancel_token: Optional[ps.CancellationToken] = None,
) -> bool:
    if not _ffmpeg_available():
        logger.error("ffmpeg not found in PATH; cannot convert %s", source)
        return False

    cmd = [
        resolve_binary("ffmpeg"),
        "-y",
        "-i",
        str(source),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        str(config["audio_output_bitrate"]),
        str(dest),
    ]
    result = _run_command(cmd, cancel_token=cancel_token)
    if result.returncode != 0:
        _log_ffmpeg_failure(source, result)
        return False

    return dest.is_file()


def _convert_photo_pillow(source: Path, dest: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow is not installed; cannot convert %s", source)
        return False

    try:
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.save(dest, "JPEG", quality=95)
        return dest.is_file()
    except Exception as exc:
        logger.error("Pillow failed for %s: %s", source, exc)
        return False


def _extract_raw_preview_array(source: Path) -> np.ndarray | None:
    """Extract embedded JPEG preview from RAW file as numpy array (in-memory)."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not available to extract RAW preview from %s", source)
        return None

    try:
        with Image.open(source) as img:
            if hasattr(img, "tag_v2"):
                tag_dict = img.tag_v2
                jpeg_data = tag_dict.get(513)
                jpeg_length = tag_dict.get(514)
                if jpeg_data and jpeg_length:
                    with open(source, "rb") as f:
                        f.seek(jpeg_data)
                        preview_data = f.read(jpeg_length)
                    with Image.open(io.BytesIO(preview_data)) as preview:
                        preview_rgb = preview.convert("RGB")
                        return np.array(preview_rgb)
    except Exception as exc:
        logger.debug("Could not extract RAW preview from %s: %s", source, exc)
        return None

    return None


def _extract_raw_preview_jpeg(source: Path, dest: Path) -> bool:
    """Try to extract the embedded JPEG preview from a RAW file to disk."""
    arr = _extract_raw_preview_array(source)
    if arr is None:
        return False
    try:
        from PIL import Image
        Image.fromarray(arr).save(dest, "JPEG", quality=95)
        return dest.is_file()
    except Exception as exc:
        logger.error("Failed to save RAW preview for %s: %s", source, exc)
        return False


def _rawpy_postprocess_worker(source_path: str, dest_path: str) -> bool:
    """Worker function run in a separate process to postprocess RAW images."""
    import rawpy
    from PIL import Image
    with rawpy.imread(source_path) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            output_color=rawpy.ColorSpace.sRGB,
            output_bps=8,
        )
    Image.fromarray(rgb).save(dest_path, "JPEG", quality=95)
    return True


def _convert_photo_raw(source: Path, dest: Path, timeout_sec: int, strategy: str) -> bool:
    strategy = strategy.lower()
    if strategy == "preview":
        return _extract_raw_preview_jpeg(source, dest)

    try:
        import rawpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        logger.warning("rawpy/Pillow not available for %s: %s; trying preview extraction", source, exc)
        return _extract_raw_preview_jpeg(source, dest)

    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    try:
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
    except OSError:
        pass

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_rawpy_postprocess_worker, str(source), str(tmp_dest))
        try:
            future.result(timeout=timeout_sec)
        except _FuturesTimeout:
            logger.warning(
                "rawpy.postprocess timed out for %s after %s seconds; extracting preview instead",
                source,
                timeout_sec,
            )
            future.cancel()
            try:
                if tmp_dest.exists():
                    tmp_dest.unlink(missing_ok=True)
            except OSError:
                pass
            if strategy == "raw":
                return False
            return _extract_raw_preview_jpeg(source, dest)
        except Exception as exc:
            logger.warning("rawpy failed for %s: %s; trying preview extraction", source, exc)
            try:
                if tmp_dest.exists():
                    tmp_dest.unlink(missing_ok=True)
            except OSError:
                pass
            if strategy == "raw":
                return False
            return _extract_raw_preview_jpeg(source, dest)
    except Exception as exc:
        logger.warning("rawpy multiprocessing failed for %s: %s; trying preview extraction", source, exc)
        try:
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
        except OSError:
            pass
        if strategy == "raw":
            return False
        return _extract_raw_preview_jpeg(source, dest)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    try:
        tmp_dest.replace(dest)
    except OSError as exc:
        logger.error("Failed to move RAW conversion result for %s: %s", source, exc)
        try:
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
        except OSError:
            pass
        if strategy == "raw":
            return False
        return _extract_raw_preview_jpeg(source, dest)

    return dest.is_file()


def _convert_photo(
    source: Path, 
    dest: Path, 
    extension: str, 
    timeout_sec: int, 
    strategy: str,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> tuple[bool, np.ndarray | None]:
    """
    Convert photo file. For RAW with preview strategy, optionally return in-memory array.
    """
    ext = extension.lower()
    if ext in RAW_EXTENSIONS:
        strategy = strategy.lower()
        if strategy in ("preview", "auto"):
            arr = _extract_raw_preview_array(source)
            if arr is not None:
                return True, arr
            if strategy == "preview":
                return False, None
        success = _convert_photo_raw(source, dest, timeout_sec, strategy)
        return success, None
    success = _convert_photo_pillow(source, dest)
    return success, None


def convert_file(
    record: FileRecord,
    config: dict[str, Any],
    work_dir: Path | str | None = None,
    dry_run: bool = False,
    cancel_token: Optional[ps.CancellationToken] = None,
    sub_progress: SubProgressCallback | None = None,
) -> ConvertedFileRecord:
    """
    Convert one FileRecord to a canonical file in the work directory.
    """
    ps.check_cancelled(cancel_token)
    result: ConvertedFileRecord = dict(record)
    source = Path(record["original_path"])

    if not source.is_file():
        logger.error("Source file not found: %s", source)
        result["skipped"] = True
        return result

    target_dir = Path(work_dir) if work_dir is not None else get_work_dir()
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    suffix = _canonical_extension(record["detected_type"])
    dest = _allocate_output_path(target_dir, source, suffix)

    if dry_run:
        result["converted_path"] = str(dest.resolve())
        return result

    success = False
    image_array = None
    
    if _is_canonical(record):
        try:
            shutil.copy2(source, dest)
            success = dest.is_file()
            if success and sub_progress:
                sub_progress(1.0)
        except OSError as exc:
            logger.error("Failed to copy canonical file %s: %s", source, exc)
    elif record["detected_type"] == "video":
        success = _convert_video(source, dest, config, sub_progress=sub_progress, cancel_token=cancel_token)
    elif record["detected_type"] == "audio":
        success = _convert_audio(source, dest, config, cancel_token=cancel_token)
        if success and sub_progress:
            sub_progress(1.0)
    elif record["detected_type"] == "photo":
        convert_result = _convert_photo(
            source,
            dest,
            record["extension"],
            config["raw_conversion_timeout_sec"],
            config["raw_conversion_strategy"],
            cancel_token=cancel_token,
        )
        if isinstance(convert_result, tuple):
            success, image_array = convert_result
        else:
            success = bool(convert_result)
            image_array = None
        if success and sub_progress:
            sub_progress(1.0)
    else:
        logger.error("Unsupported detected_type for conversion: %s", record["detected_type"])

    if success:
        if image_array is not None:
            try:
                from PIL import Image
                Image.fromarray(image_array).save(dest, "JPEG", quality=95)
                result["converted_path"] = str(dest.resolve())
                result["image_array"] = image_array
            except Exception as exc:
                logger.error("Failed to save in-memory image for %s: %s", source, exc)
                result["skipped"] = True
        else:
            result["converted_path"] = str(dest.resolve())
    else:
        result["skipped"] = True
        if dest.exists():
            try:
                dest.unlink(missing_ok=True)
            except PermissionError as exc:
                logger.warning("Could not remove failed output %s: %s", dest, exc)

    return result
