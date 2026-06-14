"""Tests for qc_video — steady-shot-at-least-5-sec approach.

Video QC now only produces "pass" or "rejected" — no "review" band.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from config_loader import DEFAULT_CONFIG
from qc_video import QCResult, analyze_video

RNG = np.random.default_rng(42)


@pytest.fixture
def config() -> dict[str, Any]:
    """Defaults with standard thresholds for steady-shot detection."""
    cfg = dict(DEFAULT_CONFIG)
    cfg["min_video_duration_sec"] = 5.0
    cfg["blur_threshold"] = 60.0
    cfg["exposure_low_threshold"] = 30
    cfg["exposure_high_threshold"] = 225
    cfg["shake_threshold"] = 30.0
    return cfg


def _make_mp4_with_ffmpeg(path: Path, duration_sec: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=64x64:d={duration_sec}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def require_fftools() -> None:
    try:
        subprocess.run(["ffprobe", "-version"], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg/ffprobe not available")


# --- Duration checks ---

def test_short_clip_duration_rejected(tmp_path: Path, config: dict[str, Any], require_fftools: None) -> None:
    """Clip below min duration -> rejected."""
    path = tmp_path / "short.mp4"
    _make_mp4_with_ffmpeg(path, 2.0)
    result = analyze_video(path, config)
    assert result["duration_check"] == "rejected"
    assert result["steady_shot_check"] == "rejected"
    assert any("below minimum" in r.lower() for r in result["reasons"])


def test_clip_at_min_duration_passes_duration(tmp_path: Path, config: dict[str, Any], require_fftools: None) -> None:
    """Clip at exactly min duration -> duration_check passes."""
    path = tmp_path / "min.mp4"
    _make_mp4_with_ffmpeg(path, 5.0)
    result = analyze_video(path, config)
    assert result["duration_check"] == "pass"


def test_ffprobe_failure_rejected(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If ffprobe can't read duration -> rejected."""
    path = tmp_path / "missing.mp4"
    path.write_bytes(b"")
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: None)
    result = analyze_video(path, config)
    assert result["duration_check"] == "rejected"
    assert result["steady_shot_check"] == "rejected"
    assert any("could not read duration" in r.lower() for r in result["reasons"])


# --- Steady shot detection (integration-like with mocks) ---

def test_steady_shot_found(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clip with a steady-shot window found -> pass."""
    path = tmp_path / "good.mp4"
    path.touch()
    
    # Mock duration
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)

    # Mock cv2.VideoCapture
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {
        cv2.CAP_PROP_FPS: 30.0,
        cv2.CAP_PROP_FRAME_COUNT: 300
    }.get(prop, 0)
    
    # Create enough "good" frames (sharp and exposed)
    # We need 11 consecutive good frames at 2 FPS to pass 5 seconds
    good_frame = RNG.integers(100, 200, (64, 64, 3), dtype=np.uint8)
    
    # Return 20 frames then stop
    mock_cap.read.side_effect = [(True, good_frame.copy()) for _ in range(20)] + [(False, None)]
    mock_cap.grab.side_effect = [True] * 100 + [False]

    with patch("cv2.VideoCapture", return_value=mock_cap):
        # We also need to mock _shake_magnitude_for_pair to return low shake
        with patch("qc_video._shake_magnitude_for_pair", return_value=0.1):
            result = analyze_video(path, config)

    assert result["duration_check"] == "pass"
    assert result["steady_shot_check"] == "pass"
    assert result["reasons"] == []


def test_no_steady_shot_found(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clip where no window is steady enough -> rejected."""
    path = tmp_path / "bad.mp4"
    path.touch()
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {
        cv2.CAP_PROP_FPS: 30.0,
        cv2.CAP_PROP_FRAME_COUNT: 300
    }.get(prop, 0)
    
    # All frames are blurry (uniform grey)
    blurry_frame = np.full((64, 64, 3), 128, dtype=np.uint8)
    mock_cap.read.side_effect = [(True, blurry_frame.copy()) for _ in range(20)] + [(False, None)]
    mock_cap.grab.side_effect = [True] * 100 + [False]

    with patch("cv2.VideoCapture", return_value=mock_cap):
        result = analyze_video(path, config)

    assert result["steady_shot_check"] == "rejected"
    assert any("No 5.0-second window" in r for r in result["reasons"])


def test_opencv_cannot_open_video(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If OpenCV fails to read -> rejected."""
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"garbage")
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    
    with patch("cv2.VideoCapture", return_value=mock_cap):
        result = analyze_video(path, config)
    
    assert result["steady_shot_check"] == "rejected"
    assert any("OpenCV cannot open video" in r for r in result["reasons"])


def test_qc_result_typing(tmp_path: Path, config: dict[str, Any], require_fftools: None) -> None:
    """Verify QCResult has expected keys and values."""
    path = tmp_path / "typed.mp4"
    _make_mp4_with_ffmpeg(path, 6.0)
    result: QCResult = analyze_video(path, config)
    for key in ("duration_check", "steady_shot_check"):
        assert result[key] in ("pass", "rejected")
    assert isinstance(result["reasons"], list)
