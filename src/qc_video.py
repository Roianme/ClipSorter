"""Video quality checks: find at least 5 consecutive seconds of a steady, not blurry, well-exposed shot.

Only two outcomes for video: "pass" (review) or "rejected" (defects).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Literal, TypedDict

import cv2
import numpy as np

logger = logging.getLogger(__name__)

QCLevel = Literal["pass", "rejected"]

# General QCResult that covers all media types.
# Video uses: duration_check, steady_shot_check
# Photo uses: duration_check, blur_check, content_check, saturation_check,
#             entropy_check, exposure_check, shake_check
# Audio uses: duration_check, exposure_check (silence)


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
    cmd = [
        "ffprobe",
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


def _read_frames_for_window(
    path: Path,
    start_sec: float,
    window_duration_sec: float,
    fps: float = 30.0,
) -> list[np.ndarray] | None:
    """Read frames from start_sec for window_duration_sec at ~fps."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        logger.warning("OpenCV cannot open video: %s", path)
        return None

    frames: list[np.ndarray] = []
    try:
        total_frames = int(window_duration_sec * fps)
        for i in range(total_frames):
            t = start_sec + i / fps
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frames.append(frame)
    finally:
        cap.release()

    # Require at least 50% of expected frames
    min_frames = max(5, int(window_duration_sec * fps * 0.5))
    if len(frames) < min_frames:
        return None
    return frames


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


def _window_has_steady_shot(
    frames: list[np.ndarray],
    blur_threshold: float,
    exposure_low: int,
    exposure_high: int,
    shake_threshold: float,
) -> bool:
    """
    Check if frames contain at least 5 contiguous frames where every frame is
    simultaneously: not blurry, well-exposed, and not shaky with neighbours.

    At ~30fps read rate, 5 frames ≈ 5 seconds (since we advance by 1 sec).
    """
    if len(frames) < 5:
        return False

    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    n = len(frames)

    # Per-frame quality flag: sharp + exposed
    frame_ok = []
    for i in range(n):
        lap_var = _laplacian_variance_gray(grays[i])
        brightness = float(grays[i].mean())
        is_sharp = lap_var >= blur_threshold
        is_exposed = exposure_low <= brightness <= exposure_high
        frame_ok.append(is_sharp and is_exposed)

    # Shake check between consecutive frame pairs
    shake_ok = [True] * (n - 1)  # index i = transition between frame i and i+1
    for i in range(n - 1):
        mag = _shake_magnitude_for_pair(grays[i], grays[i + 1])
        shake_ok[i] = mag <= shake_threshold

    # Find longest contiguous run where:
    #   - each frame passes frame_ok
    #   - the transition INTO the frame is shake_ok (if not first)
    longest_run = 0
    current_run = 0
    for i in range(n):
        transition_ok = (i == 0) or shake_ok[i - 1]
        if frame_ok[i] and transition_ok:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0

    # Require at least 5 consecutive good frames
    MIN_GOOD_FRAMES = 5
    return longest_run >= MIN_GOOD_FRAMES


def analyze_video(path: Path | str, config: dict[str, Any]) -> QCResult:
    """
    Determine if a video clip has at least 5 consecutive seconds of a steady,
    non-blurry, well-exposed shot.

    Returns:
        QCResult with:
            duration_check: "pass" if >= min duration, else "rejected"
            steady_shot_check: "pass" if steady shot found, else "rejected"
    """
    video_path = Path(path)
    reasons: list[str] = []

    # --- Duration check ---
    duration_sec = _run_ffprobe_duration_seconds(video_path)
    min_sec = float(config["min_video_duration_sec"])

    if duration_sec is None:
        duration_check: QCLevel = "rejected"
        reasons.append("Could not read duration (ffprobe failed or missing metadata)")
    elif duration_sec < min_sec:
        duration_check = "rejected"
        reasons.append(
            f"Duration {duration_sec:.2f}s is below minimum {min_sec}s",
        )
    else:
        duration_check = "pass"

    if duration_check == "rejected":
        return QCResult(
            duration_check=duration_check,
            steady_shot_check="rejected",
            reasons=reasons,
        )

    # --- Steady shot check: scan sliding 5-second windows ---
    blur_threshold = float(config["blur_threshold"])
    exposure_low = int(config["exposure_low_threshold"])
    exposure_high = int(config["exposure_high_threshold"])
    shake_threshold = float(config["shake_threshold"])
    window_sec = 5.0
    slide_step = 1.0  # slide by 1 second each iteration

    steady_shot_found = False
    current_start = 0.0

    while current_start + window_sec <= duration_sec:
        frames = _read_frames_for_window(video_path, current_start, window_sec)
        if frames is None:
            current_start += slide_step
            continue

        if _window_has_steady_shot(
            frames,
            blur_threshold,
            exposure_low,
            exposure_high,
            shake_threshold,
        ):
            steady_shot_found = True
            break

        current_start += slide_step

    if steady_shot_found:
        steady_shot_check: QCLevel = "pass"
    else:
        steady_shot_check = "rejected"
        reasons.append(
            "No 5-second window found with steady, sharp, well-exposed shot"
        )

    return QCResult(
        duration_check=duration_check,
        steady_shot_check=steady_shot_check,
        reasons=reasons,
    )
