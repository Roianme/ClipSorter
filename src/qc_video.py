"""Video quality checks: find at least 5 consecutive seconds of a steady, not blurry, well-exposed shot.

Only two outcomes for video: "pass" (review) or "rejected" (defects).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, TypedDict, Callable, Optional

import cv2
import numpy as np

# Import binary_resolver
from src.binary_resolver import resolve_binary # Consistent import

from src.cancellation import CancellationToken, check_cancelled

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


from src.video_utils import _run_ffprobe_duration_seconds


def _laplacian_variance_gray(gray: np.ndarray) -> float:
    if gray.size == 0:
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


from src.video_utils import _sample_frame_timestamps


from src.video_utils import _read_sampled_frames


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
    sub_progress: SubProgressCallback | None = None,
    cancel_token: Optional[CancellationToken] = None,
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
            check_cancelled(cancel_token)
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
