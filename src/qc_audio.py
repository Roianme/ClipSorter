"""Audio quality checks: duration and silence."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from qc_video import QCLevel, QCResult, _run_ffprobe_duration_seconds
from src.cancellation import CancellationToken, check_cancelled
from typing import Optional

logger = logging.getLogger(__name__)


def _silence_ratio(path: Path, silence_rms_threshold: float, cancel_token: Optional[CancellationToken] = None) -> float | None:
    """Fraction of RMS frames below threshold; None if librosa cannot analyze."""
    check_cancelled(cancel_token)
    try:
        waveform, _sample_rate = librosa.load(path, sr=None, mono=True)
    except Exception as exc:
        logger.warning("librosa failed for %s: %s", path, exc)
        return None

    if waveform.size == 0:
        return 1.0

    rms = librosa.feature.rms(y=waveform)[0]
    if rms.size == 0:
        return 1.0

    silent_frames = int(np.sum(rms < silence_rms_threshold))
    return silent_frames / float(rms.size)


def analyze_audio(
    path: Path | str,
    config: dict[str, Any],
    cancel_token: Optional[CancellationToken] = None,
) -> QCResult:
    """
    Run audio QC checks.

    blur_check and shake_check are always pass (not applicable).
    exposure_check carries the silence result for this media type.
    """
    check_cancelled(cancel_token)
    audio_path = Path(path)
    reasons: list[str] = []

    duration_sec = _run_ffprobe_duration_seconds(audio_path)
    min_sec = float(config["min_audio_duration_sec"])

    if duration_sec is None:
        duration_check: QCLevel = "review"
        reasons.append("Could not read duration (ffprobe failed or missing metadata)")
    elif duration_sec < min_sec:
        duration_check = "rejected"
        reasons.append(
            f"Duration {duration_sec:.2f}s is below minimum {min_sec}s",
        )
    else:
        duration_check = "pass"

    check_cancelled(cancel_token)
    silence_ratio = _silence_ratio(audio_path, float(config["silence_rms_threshold"]), cancel_token=cancel_token)
    silence_ratio_threshold = float(config["silence_ratio_threshold"])

    if silence_ratio is None:
        silence_check: QCLevel = "review"
        reasons.append("Could not analyze silence (librosa failed)")
    elif silence_ratio > silence_ratio_threshold:
        silence_check = "rejected"
        reasons.append(
            f"Silence: {100.0 * silence_ratio:.1f}% of frames below RMS threshold "
            f"{config['silence_rms_threshold']} (limit {100.0 * silence_ratio_threshold:.1f}%)",
        )
    else:
        silence_check = "pass"

    return QCResult(
        duration_check=duration_check,
        blur_check="pass",
        exposure_check=silence_check,
        shake_check="pass",
        reasons=reasons,
    )
