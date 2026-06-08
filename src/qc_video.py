"""Video quality checks: find at least 5 consecutive seconds of a steady, not blurry, well-exposed shot.

Only two outcomes for video: "pass" (review) or "rejected" (defects).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Literal, TypedDict, Callable, Optional

import cv2
import numpy as np

# Import binary_resolver
from src.binary_resolver import resolve_binary # Consistent import

logger = logging.getLogger(__name__)

QCLevel = Literal["pass", "rejected"]

SubProgressCallback = Callable[[float], None]

# General QCResult that covers all media types.
class QCResult(TypedDict, total=False):
    duration_check: QCLevel
    steady_shot_check: QCLevel
    blur_check: QCLevel
    content_check: QCLevel
    saturation_check: QCLevel
    entropy_check: QCLevel
    exposure_check: QCLevel
    shake_check: QCLevel
    reasons: list[str]


def _run_ffprobe_duration_seconds(path: Path) -> float | None:
    try:
        ffprobe_path = resolve_binary("ffprobe")
    except FileNotFoundError:
        logger.warning("ffprobe not found; cannot read video duration for %s", path)
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return None

    if result.returncode != 0:
        logger.warning("ffprobe returned %s for %s: %s", result.returncode, path, result.stderr.strip())
        return None

    text = result.stdout.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        logger.warning("ffprobe gave non-numeric duration for %s: %r", path, text)
        return None


def _laplacian_variance_gray(gray: np.ndarray) -> float:
    if gray.size == 0:
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _sample_frame_timestamps(duration_sec: float, sample_count: int) -> list[float]:
    if sample_count <= 0:
        return []
    if duration_sec <= 0:
        return [0.0] * sample_count
    if sample_count == 1:
        return [min(duration_sec / 2.0, max(duration_sec - 1e-3, 0.0))]
    return [duration_sec * i / (sample_count - 1) for i in range(sample_count)]


def _read_sampled_frames(
    path: Path,
    duration_sec: float | None,
    sample_count: int,
) -> tuple[list[np.ndarray] | None, str | None]:
    """Return list of BGR frames or None if OpenCV cannot read.

    Retained for duplicate detection in video pipeline.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        logger.warning("OpenCV cannot open video: %s", path)
        return None, "OpenCV cannot open video"

    frames: list[np.ndarray] = []
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


def _mean_brightness_bgr(frame: np.ndarray) -> float:
    """Mean brightness of a BGR frame. Retained for debug_image_metrics."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def _shake_magnitude_for_pair(prev_gray: np.ndarray, gray: np.ndarray) -> float:
    """Mean optical-flow magnitude between two consecutive grayscale frames."""
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray,
        gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    return float(mag.mean())


SAMPLE_FPS = 2.0
WINDOW_DURATION_SEC = 5.0
# At 2 FPS, we need 11 frames to cover exactly 5.0 seconds (T=0, 0.5, 1.0, ..., 5.0)
MIN_CONSECUTIVE_GOOD_FRAMES = int(SAMPLE_FPS * WINDOW_DURATION_SEC) + 1


def _resize_for_analysis(frame: np.ndarray, height: int = 240) -> np.ndarray:
    """Downscale frame for faster QC analysis."""
    h, w = frame.shape[:2]
    if h <= height:
        return frame
    width = int(w * (height / h))
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def analyze_video(
    path: Path | str, 
    config: dict[str, Any],
    sub_progress: SubProgressCallback | None = None
) -> QCResult:
    """
    Determine if a video clip has at least 5 consecutive seconds of a steady,
    non-blurry, well-exposed shot.

    Optimised version: single pass, reduced sampling rate, downscaled frames.
    """
    video_path = Path(path)
    reasons: list[str] = []

    # --- Duration check ---
    duration_sec = _run_ffprobe_duration_seconds(video_path)
    min_sec = float(config.get("min_video_duration_sec", 5.0))

    if duration_sec is None:
        duration_check: QCLevel = "rejected"
        reasons.append("Could not read duration (ffprobe failed or missing metadata)")
    elif duration_sec < min_sec:
        duration_check = "rejected"
        reasons.append(f"Duration {duration_sec:.2f}s is below minimum {min_sec}s")
    else:
        duration_check = "pass"

    if duration_check == "rejected":
        return QCResult(
            duration_check=duration_check,
            steady_shot_check="rejected",
            reasons=reasons,
        )

    # --- Steady shot check: single pass scan ---
    blur_threshold = float(config.get("blur_threshold", 60.0))
    exposure_low = int(config.get("exposure_low_threshold", 30))
    exposure_high = int(config.get("exposure_high_threshold", 225))
    shake_threshold = float(config.get("shake_threshold", 30.0))

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning("OpenCV cannot open video: %s", video_path)
        return QCResult(
            duration_check=duration_check,
            steady_shot_check="rejected",
            reasons=["OpenCV cannot open video for QC analysis"],
        )

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    
    # Calculate how many frames to skip between samples
    frame_step = max(1, int(fps / SAMPLE_FPS))
    
    steady_shot_found = False
    current_run = 0
    prev_gray = None
    
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        processed_frames = 0
        
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            
            processed_frames += 1
            if sub_progress and frame_count > 0:
                sub_progress(min(1.0, processed_frames / (frame_count / frame_step + 1)))

            # Analyze frame
            small_frame = _resize_for_analysis(frame)
            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
            
            # Check sharpness and exposure
            lap_var = _laplacian_variance_gray(gray)
            brightness = float(gray.mean())
            
            frame_ok = (lap_var >= blur_threshold) and (exposure_low <= brightness <= exposure_high)
            
            # Check shake with previous sampled frame
            transition_ok = True
            if prev_gray is not None:
                mag = _shake_magnitude_for_pair(prev_gray, gray)
                transition_ok = (mag <= shake_threshold)
            
            if frame_ok and transition_ok:
                current_run += 1
            else:
                # If frame is bad, reset run. 
                # If frame is good but transition was shaky, the new run starts with this frame.
                current_run = 1 if frame_ok else 0
            
            if current_run >= MIN_CONSECUTIVE_GOOD_FRAMES:
                steady_shot_found = True
                if sub_progress:
                    sub_progress(1.0)
                break
            
            prev_gray = gray
            
            # Fast-forward to next sample point
            for _ in range(frame_step - 1):
                if not cap.grab():
                    break
                processed_frames += 0 # grab doesn't count as full frame decode
    finally:
        cap.release()

    if steady_shot_found:
        steady_shot_check: QCLevel = "pass"
    else:
        steady_shot_check = "rejected"
        reasons.append(
            f"No {WINDOW_DURATION_SEC:.1f}-second window found with steady, sharp, well-exposed shot"
        )

    return QCResult(
        duration_check=duration_check,
        steady_shot_check=steady_shot_check,
        reasons=reasons,
    )
