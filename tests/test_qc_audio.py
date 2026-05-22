"""Tests for qc_audio (Step 6)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from config_loader import DEFAULT_CONFIG
from qc_audio import analyze_audio
from qc_video import QCResult


@pytest.fixture
def config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    cfg["min_audio_duration_sec"] = 3.0
    cfg["silence_ratio_threshold"] = 0.80
    cfg["silence_rms_threshold"] = 0.01
    return cfg


@pytest.fixture
def require_fftools() -> None:
    try:
        subprocess.run(["ffprobe", "-version"], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg/ffprobe not available")


def _make_wav(path: Path, duration_sec: float, *, silent: bool = False) -> None:
    if silent:
        lavfi = f"anullsrc=r=44100:cl=mono:d={duration_sec}"
    else:
        lavfi = f"sine=frequency=440:duration={duration_sec}"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            lavfi,
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_audio_qc_structure_and_not_applicable_fields(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    path = tmp_path / "tone.wav"
    _make_wav(path, 5.0, silent=False)

    result: QCResult = analyze_audio(path, config)
    assert set(result.keys()) == {
        "duration_check",
        "blur_check",
        "exposure_check",
        "shake_check",
        "reasons",
    }
    assert result["blur_check"] == "pass"
    assert result["shake_check"] == "pass"


def test_short_audio_duration_rejected(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    path = tmp_path / "short.wav"
    _make_wav(path, 1.0, silent=False)

    result = analyze_audio(path, config)
    assert result["duration_check"] == "rejected"
    assert any("below minimum" in reason.lower() for reason in result["reasons"])


def test_long_audio_duration_pass(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    path = tmp_path / "long.wav"
    _make_wav(path, 5.0, silent=False)

    result = analyze_audio(path, config)
    assert result["duration_check"] == "pass"


def test_mostly_silent_audio_rejected(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    path = tmp_path / "silent.wav"
    _make_wav(path, 5.0, silent=True)

    result = analyze_audio(path, config)
    assert result["exposure_check"] == "rejected"
    assert any("silence" in reason.lower() for reason in result["reasons"])


def test_non_silent_audio_silence_pass(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    path = tmp_path / "tone.wav"
    _make_wav(path, 5.0, silent=False)

    result = analyze_audio(path, config)
    assert result["exposure_check"] == "pass"


def test_ffprobe_failure_duration_review(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "broken.wav"
    path.write_bytes(b"not audio")

    monkeypatch.setattr("qc_audio._run_ffprobe_duration_seconds", lambda _p: None)
    monkeypatch.setattr("qc_audio._silence_ratio", lambda *_a, **_k: 0.0)

    result = analyze_audio(path, config)
    assert result["duration_check"] == "review"
    assert any("ffprobe" in reason.lower() for reason in result["reasons"])


def test_librosa_failure_silence_review(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "x.wav"
    path.touch()

    monkeypatch.setattr("qc_audio._run_ffprobe_duration_seconds", lambda _p: 10.0)
    monkeypatch.setattr("qc_audio._silence_ratio", lambda *_a, **_k: None)

    result = analyze_audio(path, config)
    assert result["exposure_check"] == "review"
    assert any("librosa" in reason.lower() for reason in result["reasons"])


def test_blur_and_shake_always_pass_with_mocks(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "fake.wav"
    path.touch()

    monkeypatch.setattr("qc_audio._run_ffprobe_duration_seconds", lambda _p: 10.0)
    monkeypatch.setattr("qc_audio._silence_ratio", lambda *_a, **_k: 0.0)

    result = analyze_audio(path, config)
    assert result["blur_check"] == "pass"
    assert result["shake_check"] == "pass"
