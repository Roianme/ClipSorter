"""Tests for classifier — video now binary (clean/rejected), photo/audio full multi-level."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from classifier import ClassifierResult, classify_file
from config_loader import DEFAULT_CONFIG
from duplicate import DuplicatePair
from qc_video import QCResult


# --- Factory helpers for the two QC result shapes ---

def _video_qc(steady: str = "pass", reasons: list[str] | None = None) -> QCResult:
    return QCResult(
        duration_check="pass",  # type: ignore[typeddict-item]
        steady_shot_check=steady,  # type: ignore[typeddict-item]
        reasons=reasons or [],
    )


def _photo_qc(
    *,
    duration: str = "pass",
    blur: str = "pass",
    exposure: str = "pass",
    shake: str = "pass",
    reasons: list[str] | None = None,
) -> QCResult:
    return QCResult(
        duration_check=duration,  # type: ignore[typeddict-item]
        blur_check=blur,  # type: ignore[typeddict-item]
        exposure_check=exposure,  # type: ignore[typeddict-item]
        shake_check=shake,  # type: ignore[typeddict-item]
        reasons=reasons or [],
    )


@pytest.fixture
def config() -> dict[str, Any]:
    return dict(DEFAULT_CONFIG)


@pytest.fixture
def vid_path(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.touch()
    return path


@pytest.fixture
def photo_path(tmp_path: Path) -> Path:
    path = tmp_path / "photo.jpg"
    path.touch()
    return path


# ========== VIDEO TESTS (binary: clean / rejected) ==========

def test_video_steady_pass_is_clean(vid_path: Path, config: dict[str, Any]) -> None:
    result = classify_file(_video_qc(steady="pass"), [], vid_path, config, detected_type="video")
    assert result["bucket"] == "clean"
    assert result["reasons"] == []


def test_video_steady_rejected_is_rejected(vid_path: Path, config: dict[str, Any]) -> None:
    qc = _video_qc(steady="rejected", reasons=["No steady shot"])
    result = classify_file(qc, [], vid_path, config, detected_type="video")
    assert result["bucket"] == "rejected"
    assert "No steady shot" in result["reasons"]


def test_video_duplicates_ignored(vid_path: Path, config: dict[str, Any]) -> None:
    """Video ignores duplicates — always binary outcome from QC."""
    other = vid_path.parent / "other.mp4"
    other.touch()
    pair = DuplicatePair(
        file_a=str(vid_path.resolve()),
        file_b=str(other.resolve()),
        match_type="video_keyframe",
        confidence=0.85,
    )
    result = classify_file(_video_qc(steady="pass"), [pair], vid_path, config, detected_type="video")
    assert result["bucket"] == "clean", "Video should not be forced to review for duplicates"

    result2 = classify_file(_video_qc(steady="rejected"), [pair], vid_path, config, detected_type="video")
    assert result2["bucket"] == "rejected"


def test_video_burst_ignored(vid_path: Path, config: dict[str, Any]) -> None:
    """Video ignores burst groups."""
    group = {"files": [str(vid_path.resolve())], "match_type": "burst"}
    result = classify_file(_video_qc(steady="pass"), [], vid_path, config, burst_groups=[group], detected_type="video")
    assert result["bucket"] == "clean"


# ========== PHOTO / AUDIO TESTS (full multi-level) ==========

def test_photo_all_pass_is_clean(photo_path: Path, config: dict[str, Any]) -> None:
    result = classify_file(_photo_qc(), [], photo_path, config)
    assert result["bucket"] == "clean"
    assert result["reasons"] == []


def test_photo_one_review_is_review(photo_path: Path, config: dict[str, Any]) -> None:
    qc = _photo_qc(shake="review", reasons=["Shake detected"])
    result = classify_file(qc, [], photo_path, config)
    assert result["bucket"] == "review"
    assert "Shake detected" in result["reasons"]


def test_photo_one_rejected_is_rejected(photo_path: Path, config: dict[str, Any]) -> None:
    qc = _photo_qc(duration="rejected", reasons=["Too short"])
    result = classify_file(qc, [], photo_path, config)
    assert result["bucket"] == "rejected"
    assert "Too short" in result["reasons"]


def test_photo_rejected_overrides_review(photo_path: Path, config: dict[str, Any]) -> None:
    qc = _photo_qc(duration="rejected", blur="review", reasons=["Short", "Blurry"])
    result = classify_file(qc, [], photo_path, config)
    assert result["bucket"] == "rejected"


def test_photo_duplicate_forces_review(photo_path: Path, config: dict[str, Any]) -> None:
    other = photo_path.parent / "other.jpg"
    other.touch()
    pair = DuplicatePair(
        file_a=str(photo_path.resolve()),
        file_b=str(other.resolve()),
        match_type="image_hash",
        confidence=2.0,
    )
    result = classify_file(_photo_qc(), [pair], photo_path, config)
    assert result["bucket"] == "review"
    assert any("DUPLICATE of" in reason for reason in result["reasons"])


def test_photo_burst_overrides_duplicate_review(photo_path: Path, config: dict[str, Any]) -> None:
    other = photo_path.parent / "other.jpg"
    other.touch()
    pair = DuplicatePair(
        file_a=str(photo_path.resolve()),
        file_b=str(other.resolve()),
        match_type="image_hash",
        confidence=2.0,
    )
    group = {"files": [str(photo_path.resolve())], "match_type": "burst"}
    result = classify_file(_photo_qc(), [pair], photo_path, config, burst_groups=[group])
    assert result["bucket"] == "burst"


def test_photo_burst_group_forces_burst(photo_path: Path, config: dict[str, Any]) -> None:
    group = {"files": [str(photo_path.resolve())], "match_type": "burst"}
    result = classify_file(_photo_qc(), [], photo_path, config, burst_groups=[group])
    assert result["bucket"] == "burst"


def test_photo_burst_does_not_override_rejected(photo_path: Path, config: dict[str, Any]) -> None:
    qc = _photo_qc(duration="rejected", reasons=["Too short"])
    group = {"files": [str(photo_path.resolve())], "match_type": "burst"}
    result = classify_file(qc, [], photo_path, config, burst_groups=[group])
    assert result["bucket"] == "rejected"


def test_photo_duplicate_does_not_override_rejected(photo_path: Path, config: dict[str, Any]) -> None:
    other = photo_path.parent / "other.jpg"
    other.touch()
    pair = DuplicatePair(
        file_a=str(photo_path.resolve()),
        file_b=str(other.resolve()),
        match_type="image_hash",
        confidence=2.0,
    )
    qc = _photo_qc(duration="rejected", reasons=["Too short"])
    result = classify_file(qc, [pair], photo_path, config)
    assert result["bucket"] == "rejected"


def test_photo_multiple_review_still_review(photo_path: Path, config: dict[str, Any]) -> None:
    qc = _photo_qc(blur="review", exposure="review", reasons=["Blur", "Exposure"])
    result = classify_file(qc, [], photo_path, config)
    assert result["bucket"] == "review"
    assert len(result["reasons"]) == 2


def test_classifier_result_typing_photo(photo_path: Path, config: dict[str, Any]) -> None:
    result: ClassifierResult = classify_file(_photo_qc(), [], photo_path, config)
    assert result["bucket"] in ("clean", "review", "rejected")
    assert isinstance(result["reasons"], list)


def test_classifier_result_typing_video(vid_path: Path, config: dict[str, Any]) -> None:
    result: ClassifierResult = classify_file(_video_qc(steady="pass"), [], vid_path, config, detected_type="video")
    assert result["bucket"] in ("clean", "rejected")
    assert isinstance(result["reasons"], list)
