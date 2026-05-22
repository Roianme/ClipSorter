"""Tests for duplicate detection (Step 7)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

RNG = np.random.default_rng(11)

from config_loader import DEFAULT_CONFIG
from duplicate import (
    DuplicatePair,
    find_audio_duplicates,
    find_duplicates,
    find_image_duplicates,
    find_video_duplicates,
    format_duplicate_flag,
)

MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    cfg["frame_sample_count"] = 5
    cfg["duplicate_hash_threshold"] = 10
    cfg["duplicate_video_frame_match_ratio"] = 0.7
    cfg["duplicate_audio_similarity_threshold"] = 0.95
    return cfg


@pytest.fixture
def require_fftools() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not available")


def _save_png(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (32, 32), color=color).save(path)


def test_identical_images_detected(tmp_path: Path, config: dict[str, Any]) -> None:
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    _save_png(a, (200, 10, 10))
    shutil.copy2(a, b)

    pairs = find_image_duplicates([a, b], config)
    assert len(pairs) == 1
    assert pairs[0]["match_type"] == "image_hash"
    assert pairs[0]["confidence"] == 0.0


def test_different_images_not_detected(tmp_path: Path, config: dict[str, Any]) -> None:
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    Image.fromarray(RNG.integers(0, 256, (64, 64, 3), dtype=np.uint8)).save(a)
    Image.fromarray(RNG.integers(0, 256, (64, 64, 3), dtype=np.uint8)).save(b)

    pairs = find_image_duplicates([a, b], config)
    assert pairs == []


def test_image_duplicate_flag_message(tmp_path: Path, config: dict[str, Any]) -> None:
    a = tmp_path / "photo_a.jpg"
    b = tmp_path / "photo_b.jpg"
    _save_png(a, (50, 50, 50))
    shutil.copy2(a, b)

    pair = find_image_duplicates([a, b], config)[0]
    msg = format_duplicate_flag(pair, str(a.resolve()))
    assert "DUPLICATE of photo_b.jpg" in msg
    assert "hash distance: 0" in msg


def test_audio_fingerprint_duplicates(
    tmp_path: Path,
    config: dict[str, Any],
    require_fftools: None,
) -> None:
    source = tmp_path / "tone.wav"
    copy = tmp_path / "tone_copy.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    shutil.copy2(source, copy)

    pairs = find_audio_duplicates([source, copy], config)
    assert len(pairs) == 1
    assert pairs[0]["match_type"] == "audio_fingerprint"
    assert pairs[0]["confidence"] > config["duplicate_audio_similarity_threshold"]


def test_audio_duplicate_flag_message(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = DuplicatePair(
        file_a="/a/tone1.mp3",
        file_b="/a/tone2.mp3",
        match_type="audio_fingerprint",
        confidence=0.99,
    )
    msg = format_duplicate_flag(pair, "/a/tone1.mp3")
    assert msg == "DUPLICATE of tone2.mp3 (audio fingerprint match)"


def test_video_keyframe_duplicates_with_mock(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import imagehash

    video_a = tmp_path / "a.mp4"
    video_b = tmp_path / "b.mp4"
    video_a.touch()
    video_b.touch()

    shared = [imagehash.hex_to_hash("0" * 16) for _ in range(5)]

    monkeypatch.setattr("duplicate._video_keyframe_hashes", lambda _path, _cfg: list(shared))

    pairs = find_video_duplicates([video_a, video_b], config)
    assert len(pairs) == 1
    assert pairs[0]["match_type"] == "video_keyframe"
    assert pairs[0]["confidence"] == 1.0

    msg = format_duplicate_flag(pairs[0], str(video_a.resolve()))
    assert "100% keyframe match" in msg


def test_video_not_duplicate_when_ratio_low(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import imagehash

    video_a = tmp_path / "a.mp4"
    video_b = tmp_path / "b.mp4"
    video_a.touch()
    video_b.touch()

    hashes_a = [imagehash.hex_to_hash("0" * 16) for _ in range(5)]
    hashes_b = [imagehash.hex_to_hash("f" * 16) for _ in range(5)]

    def fake_hashes(path: Path, _cfg: dict[str, Any]) -> list[imagehash.ImageHash]:
        return hashes_a if path.name == "a.mp4" else hashes_b

    monkeypatch.setattr("duplicate._video_keyframe_hashes", fake_hashes)

    pairs = find_video_duplicates([video_a, video_b], config)
    assert pairs == []


def test_find_duplicates_aggregates_by_type(
    tmp_path: Path,
    config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    photo = tmp_path / "p.jpg"
    _save_png(photo, (1, 2, 3))
    photo_copy = tmp_path / "p_copy.jpg"
    shutil.copy2(photo, photo_copy)

    monkeypatch.setattr("duplicate.find_video_duplicates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "duplicate.find_audio_duplicates",
        lambda *_a, **_k: [
            DuplicatePair(
                file_a="/x/a.mp3",
                file_b="/x/b.mp3",
                match_type="audio_fingerprint",
                confidence=0.99,
            ),
        ],
    )

    pairs = find_duplicates(photo_paths=[photo, photo_copy], audio_paths=["/x/a.mp3", "/x/b.mp3"], config=config)
    assert len(pairs) == 2
    match_types = {pair["match_type"] for pair in pairs}
    assert match_types == {"image_hash", "audio_fingerprint"}


def test_pairs_normalized_lexicographically(tmp_path: Path, config: dict[str, Any]) -> None:
    z = tmp_path / "z.jpg"
    a = tmp_path / "a.jpg"
    _save_png(z, (5, 5, 5))
    shutil.copy2(z, a)

    pairs = find_image_duplicates([z, a], config)
    assert pairs[0]["file_a"] <= pairs[0]["file_b"]


def test_audio_fingerprint_cosine(monkeypatch: pytest.MonkeyPatch) -> None:
    from duplicate import _audio_fingerprint, _cosine_similarity

    monkeypatch.setattr(
        "duplicate.librosa.load",
        lambda *_a, **_k: (np.ones(22050), 22050),
    )
    monkeypatch.setattr(
        "duplicate.librosa.feature.chroma_cqt",
        lambda *_a, **_k: np.ones((12, 10)),
    )

    fp_a = _audio_fingerprint(Path("fake.wav"))
    fp_b = _audio_fingerprint(Path("fake2.wav"))
    assert fp_a is not None and fp_b is not None
    assert _cosine_similarity(fp_a, fp_b) == pytest.approx(1.0)
