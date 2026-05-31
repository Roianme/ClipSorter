"""Tests for qc_video — steady-shot-at-least-5-sec approach.

Video QC now only produces "pass" or "rejected" — no "review" band.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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
    assert any("ffprobe" in r.lower() for r in result["reasons"])


# --- Steady shot detection (integration-like with mocks) ---

def test_steady_shot_found(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clip with a steady-shot window found -> pass."""
    path = tmp_path / "good.mp4"
    path.touch()
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)

    # Mock window reads as returning valid frames
    frames = [RNG.integers(0, 256, (100, 100, 3), dtype=np.uint8).astype(np.uint8) for _ in range(30)]
    monkeypatch.setattr("qc_video._read_frames_for_window", lambda _p, _s, _w, fps=30.0: frames[:int(_w * fps)])
    # Mock the window check to simulate finding a steady shot
    monkeypatch.setattr("qc_video._window_has_steady_shot", lambda *a, **kw: True)

    result = analyze_video(path, config)
    assert result["duration_check"] == "pass"
    assert result["steady_shot_check"] == "pass"
    assert result["reasons"] == []


def test_no_steady_shot_found(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clip where no window is steady enough -> rejected."""
    path = tmp_path / "bad.mp4"
    path.touch()
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)

    frames = [np.full((100, 100, 3), 128, dtype=np.uint8) for _ in range(30)]
    monkeypatch.setattr("qc_video._read_frames_for_window", lambda _p, _s, _w, fps=30.0: frames[:int(_w * fps)])
    monkeypatch.setattr("qc_video._window_has_steady_shot", lambda *a, **kw: False)

    result = analyze_video(path, config)
    assert result["steady_shot_check"] == "rejected"
    assert any("No 5-second window" in r for r in result["reasons"])


def test_opencv_cannot_open_video(config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If OpenCV fails to read -> rejected."""
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"garbage")
    monkeypatch.setattr("qc_video._run_ffprobe_duration_seconds", lambda _p: 10.0)
    monkeypatch.setattr("qc_video._read_frames_for_window", lambda *a, **kw: None)

    result = analyze_video(path, config)
    assert result["steady_shot_check"] == "rejected"


# --- Window steady-shot unit tests ---

def test_window_has_steady_shot_yes(config: dict[str, Any]) -> None:
    """Sharp, exposed, steady frames -> True."""
    from qc_video import _window_has_steady_shot

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    frames = [RNG.integers(0, 256, (100, 100, 3), dtype=np.uint8).astype(np.uint8) for _ in range(30)]
    # Ensure good brightness
    for f in frames:
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        mean = float(gray.mean())
        if mean < exp_low or mean > exp_high:
            scale = 128.0 / max(mean, 1e-6)
            idx = frames.index(f)
            frames[idx] = np.clip(f * scale, 0, 255).astype(np.uint8)

    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is True


def test_window_has_steady_shot_blurry(config: dict[str, Any]) -> None:
    """All frames flat (blurry) -> False."""
    from qc_video import _window_has_steady_shot

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    frames = [np.full((100, 100, 3), 128, dtype=np.uint8) for _ in range(30)]
    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is False


def test_window_has_steady_shot_dark(config: dict[str, Any]) -> None:
    """All frames underexposed -> False."""
    from qc_video import _window_has_steady_shot

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    frames = [RNG.integers(0, 5, (100, 100, 3), dtype=np.uint8).astype(np.uint8) for _ in range(30)]
    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is False


def test_window_has_steady_shot_shaky(config: dict[str, Any]) -> None:
    """Frames with moving content so shake exceeds threshold -> False."""
    from qc_video import _window_has_steady_shot, _shake_magnitude_for_pair

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    frames = []
    for i in range(30):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        x = (i * 10) % 80
        frame[x:x+20, x:x+20] = [255, 255, 255]
        frames.append(frame)

    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    has_shaky = any(
        _shake_magnitude_for_pair(grays[i], grays[i + 1]) > shake_th
        for i in range(len(grays) - 1)
    )
    if not has_shaky:
        pytest.skip("Could not produce enough shake in test frames")

    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is False


def test_5_consecutive_good_frames(config: dict[str, Any]) -> None:
    """Exactly 5 good frames in a row -> True."""
    from qc_video import _window_has_steady_shot

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    sharp = RNG.integers(0, 256, (100, 100, 3), dtype=np.uint8).astype(np.uint8)
    blurry = np.full((100, 100, 3), 128, dtype=np.uint8)

    # 5 sharp then 5 blurry
    frames = [sharp.copy() for _ in range(5)] + [blurry.copy() for _ in range(5)]

    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is True


def test_4_good_frames_insufficient(config: dict[str, Any]) -> None:
    """Only 4 good frames -> False."""
    from qc_video import _window_has_steady_shot

    blur_th = float(config["blur_threshold"])
    exp_low = int(config["exposure_low_threshold"])
    exp_high = int(config["exposure_high_threshold"])
    shake_th = float(config["shake_threshold"])

    sharp = RNG.integers(0, 256, (100, 100, 3), dtype=np.uint8).astype(np.uint8)
    blurry = np.full((100, 100, 3), 128, dtype=np.uint8)

    # 4 sharp, then blurry — never find a run of 5
    frames = [sharp.copy() for _ in range(4)] + [blurry.copy() for _ in range(10)]

    result = _window_has_steady_shot(frames, blur_th, exp_low, exp_high, shake_th)
    assert result is False


def test_qc_result_typing(tmp_path: Path, config: dict[str, Any], require_fftools: None) -> None:
    """Verify QCResult has expected keys and values."""
    path = tmp_path / "typed.mp4"
    _make_mp4_with_ffmpeg(path, 6.0)
    result: QCResult = analyze_video(path, config)
    for key in ("duration_check", "steady_shot_check"):
        assert result[key] in ("pass", "rejected")
    assert isinstance(result["reasons"], list)
