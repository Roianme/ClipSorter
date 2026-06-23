"""Utility functions for video processing used across the project.

This module extracts the two helpers that were previously defined in
`src.qc_video` to break the circular import between `qc_video` and
`pipeline_shared`.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List

import cv2
import numpy as np

from src.cancellation import CancellationToken, check_cancelled

logger = logging.getLogger(__name__)

def _run_ffprobe_duration_seconds(path: Path) -> Optional[float]:
    """Run ffprobe to obtain the duration of *path* in seconds.

    Returns ``None`` if ffprobe is unavailable or the call fails.
    """
    try:
        from src.binary_resolver import resolve_binary
        ffprobe_path = resolve_binary("ffprobe")
    except FileNotFoundError:
        logger.warning("ffprobe not found; cannot read video duration for %s", path)
        return None
    except Exception as exc:
        logger.warning("Unexpected error locating ffprobe for %s: %s", path, exc)
        return None

    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    kwargs = {"capture_output": True, "text": True, "check": False, "timeout": 120}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, **kwargs)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "ffprobe returned %s for %s: %s",
            result.returncode,
            path,
            result.stderr.strip(),
        )
        return None

    text = result.stdout.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        logger.warning("ffprobe gave non-numeric duration for %s: %r", path, text)
        return None

def _sample_frame_timestamps(duration_sec: float, sample_count: int) -> List[float]:
    """Generate *sample_count* timestamps evenly spaced across *duration_sec*.
    Helper used by :func:`_read_sampled_frames`.
    """
    if sample_count <= 0:
        return []
    if duration_sec <= 0:
        return [0.0] * sample_count
    if sample_count == 1:
        return [min(duration_sec / 2.0, max(duration_sec - 1e-3, 0.0))]
    return [duration_sec * i / (sample_count - 1) for i in range(sample_count)]

def _read_sampled_frames(
    path: Path,
    duration_sec: Optional[float],
    sample_count: int,
) -> Tuple[Optional[List[np.ndarray]], Optional[str]]:
    """Return a list of BGR frames sampled from *path*.

    The function reads *sample_count* frames from *path*. If *duration_sec* is
    provided it is used to calculate evenly‑spaced timestamps via
    :func:`_sample_frame_timestamps`. Returns a tuple ``(frames, error)`` where
    ``frames`` is ``None`` on failure.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        logger.warning("OpenCV cannot open video: %s", path)
        return None, "OpenCV cannot open video"

    frames: List[np.ndarray] = []
    try:
        if duration_sec is not None and duration_sec > 0:
            timestamps = _sample_frame_timestamps(duration_sec, sample_count)
            for t_sec in timestamps:
                cap.set(cv2.CAP_PROP_POS_MSEC, t_sec * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                if not ok or frame is None:
                    logger.warning("Failed to read frame at %.3fs in %s", t_sec, path)
                    return None, "Failed to read sampled frames"
                frames.append(frame)
        else:
            for _ in range(sample_count):
                ok, frame = cap.read()
                if not ok or frame is None:
                    if not frames:
                        return None, "Failed to read sampled frames"
                    frames.append(frames[-1])
                    continue
                frames.append(frame)
    finally:
        cap.release()

    return frames, None
