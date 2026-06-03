"""Cross-file duplicate detection for photos, videos, and audio."""

from __future__ import annotations

import logging
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, TypedDict

import cv2
import imagehash
import librosa
import numpy as np
from PIL import Image

from qc_video import _read_sampled_frames, _run_ffprobe_duration_seconds
import pipeline_shared as ps

logger = logging.getLogger(__name__)

MatchType = Literal["image_hash", "video_keyframe", "audio_fingerprint"]


class DuplicatePair(TypedDict):
    file_a: str
    file_b: str
    match_type: MatchType
    confidence: float


class BurstGroup(TypedDict):
    files: list[str]
    match_type: Literal["burst"]


def _normalize_pair(path_a: str, path_b: str) -> tuple[str, str]:
    if path_a <= path_b:
        return path_a, path_b
    return path_b, path_a


def format_duplicate_flag(pair: DuplicatePair, path: str) -> str:
    """Log/report note: which file is a suspected duplicate of which."""
    path = str(Path(path).resolve())
    file_a = str(Path(pair["file_a"]).resolve())
    file_b = str(Path(pair["file_b"]).resolve())
    other_name = Path(file_b).name if path == file_a else Path(file_a).name

    match pair["match_type"]:
        case "image_hash":
            return f"DUPLICATE of {other_name} (hash distance: {int(pair['confidence'])})"
        case "video_keyframe":
            return f"DUPLICATE of {other_name} ({100.0 * pair['confidence']:.0f}% keyframe match)"
        case "audio_fingerprint":
            return f"DUPLICATE of {other_name} (audio fingerprint match)"
        case _:
            return f"DUPLICATE of {other_name}"


def _photo_phash(path: Path) -> imagehash.ImageHash | None:
    try:
        with Image.open(path) as image:
            return imagehash.phash(image.convert("RGB"))
    except Exception as exc:
        logger.warning("Could not hash photo %s: %s", path, exc)
        return None


def _video_keyframe_hashes(path: Path, config: dict[str, Any]) -> list[imagehash.ImageHash] | None:
    duration = _run_ffprobe_duration_seconds(path)
    sample_count = int(config["frame_sample_count"])
    frames, _error = _read_sampled_frames(path, duration, sample_count)
    if not frames:
        logger.warning("Could not extract keyframes for duplicate check: %s", path)
        return None

    hashes: list[imagehash.ImageHash] = []
    for frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hashes.append(imagehash.phash(Image.fromarray(rgb)))
    return hashes


def _audio_fingerprint(path: Path) -> np.ndarray | None:
    try:
        waveform, sample_rate = librosa.load(path, sr=None, mono=True)
        chroma = librosa.feature.chroma_cqt(y=waveform, sr=sample_rate)
        return chroma.mean(axis=1)
    except Exception as exc:
        logger.warning("Could not fingerprint audio %s: %s", path, exc)
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _keyframe_match_ratio(
    hashes_a: list[imagehash.ImageHash],
    hashes_b: list[imagehash.ImageHash],
    hash_threshold: int,
) -> float:
    count = min(len(hashes_a), len(hashes_b))
    if count == 0:
        return 0.0
    matches = sum(1 for i in range(count) if hashes_a[i] - hashes_b[i] < hash_threshold)
    return matches / count


def find_image_duplicates(photo_paths: list[str | Path], config: dict[str, Any]) -> list[DuplicatePair]:
    threshold = int(config["duplicate_hash_threshold"])
    indexed: list[tuple[str, imagehash.ImageHash]] = []

    for raw_path in photo_paths:
        path = Path(raw_path)
        phash = _photo_phash(path)
        if phash is not None:
            indexed.append((str(path.resolve()), phash))

    pairs: list[DuplicatePair] = []
    for (path_a, hash_a), (path_b, hash_b) in combinations(indexed, 2):
        distance = hash_a - hash_b
        if distance < threshold:
            file_a, file_b = _normalize_pair(path_a, path_b)
            pairs.append(
                DuplicatePair(
                    file_a=file_a,
                    file_b=file_b,
                    match_type="image_hash",
                    confidence=float(distance),
                ),
            )
            logger.info(
                "Image duplicate: %s <-> %s (hash distance %s)",
                Path(file_a).name,
                Path(file_b).name,
                distance,
            )

    return pairs


def find_burst_groups(photo_paths: list[str | Path], config: dict[str, Any], cancel_token: Optional[ps.CancellationToken] = None) -> list[BurstGroup]:
    ps.check_cancelled(cancel_token)
    burst_threshold = int(config["burst_hash_distance_threshold"])
    exact_threshold = int(config["duplicate_hash_threshold"])
    min_group_size = int(config["burst_min_group_size"])

    indexed: list[tuple[str, imagehash.ImageHash]] = []
    for raw_path in photo_paths:
        ps.check_cancelled(cancel_token)
        path = Path(raw_path)
        phash = _photo_phash(path)
        if phash is not None:
            indexed.append((str(path.resolve()), phash))

    sorted_indexed = sorted(indexed, key=lambda item: Path(item[0]).name)
    adjacency: dict[str, set[str]] = {path: set() for path, _ in sorted_indexed}
    for (path_a, hash_a), (path_b, hash_b) in combinations(sorted_indexed, 2):
        distance = hash_a - hash_b
        logger.debug(
            "BURST CHECK: %s vs %s → distance %s",
            Path(path_a).name,
            Path(path_b).name,
            distance,
        )
        if exact_threshold <= distance <= burst_threshold:
            adjacency[path_a].add(path_b)
            adjacency[path_b].add(path_a)

    groups: list[BurstGroup] = []
    visited: set[str] = set()
    for path in adjacency:
        if path in visited or not adjacency[path]:
            continue

        component: set[str] = set()
        stack = [path]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            for neighbor in adjacency[current]:
                if neighbor not in component:
                    stack.append(neighbor)

        visited.update(component)
        if len(component) >= min_group_size:
            groups.append(
                BurstGroup(
                    files=sorted(component),
                    match_type="burst",
                )
            )

    return groups


def find_video_duplicates(video_paths: list[str | Path], config: dict[str, Any]) -> list[DuplicatePair]:
    hash_threshold = int(config["duplicate_hash_threshold"])
    match_ratio_threshold = float(config["duplicate_video_frame_match_ratio"])
    indexed: list[tuple[str, list[imagehash.ImageHash]]] = []

    for raw_path in video_paths:
        path = Path(raw_path)
        hashes = _video_keyframe_hashes(path, config)
        if hashes:
            indexed.append((str(path.resolve()), hashes))

    pairs: list[DuplicatePair] = []
    for (path_a, hashes_a), (path_b, hashes_b) in combinations(indexed, 2):
        ratio = _keyframe_match_ratio(hashes_a, hashes_b, hash_threshold)
        if ratio > match_ratio_threshold:
            file_a, file_b = _normalize_pair(path_a, path_b)
            pairs.append(
                DuplicatePair(
                    file_a=file_a,
                    file_b=file_b,
                    match_type="video_keyframe",
                    confidence=ratio,
                ),
            )
            logger.info(
                "Video duplicate: %s <-> %s (%.0f%% keyframe match)",
                Path(file_a).name,
                Path(file_b).name,
                100.0 * ratio,
            )

    return pairs


def find_audio_duplicates(audio_paths: list[str | Path], config: dict[str, Any]) -> list[DuplicatePair]:
    similarity_threshold = float(config["duplicate_audio_similarity_threshold"])
    indexed: list[tuple[str, np.ndarray]] = []

    for raw_path in audio_paths:
        path = Path(raw_path)
        fingerprint = _audio_fingerprint(path)
        if fingerprint is not None:
            indexed.append((str(path.resolve()), fingerprint))

    pairs: list[DuplicatePair] = []
    for (path_a, fp_a), (path_b, fp_b) in combinations(indexed, 2):
        similarity = _cosine_similarity(fp_a, fp_b)
        if similarity > similarity_threshold:
            file_a, file_b = _normalize_pair(path_a, path_b)
            pairs.append(
                DuplicatePair(
                    file_a=file_a,
                    file_b=file_b,
                    match_type="audio_fingerprint",
                    confidence=similarity,
                ),
            )
            logger.info(
                "Audio duplicate: %s <-> %s (similarity %.3f)",
                Path(file_a).name,
                Path(file_b).name,
                similarity,
            )

    return pairs


def find_duplicates(
    photo_paths: list[str | Path] | None = None,
    video_paths: list[str | Path] | None = None,
    audio_paths: list[str | Path] | None = None,
    config: dict[str, Any] | None = None,
) -> list[DuplicatePair]:
    """
    Run duplicate detection across all provided media paths.

    Returns duplicate pairs only; never deletes files. Downstream classifier
    should send both files to review regardless of QC scores.
    """
    from config_loader import DEFAULT_CONFIG

    cfg = config if config is not None else DEFAULT_CONFIG
    photos = list(photo_paths or [])
    videos = list(video_paths or [])
    audios = list(audio_paths or [])

    results: list[DuplicatePair] = []
    results.extend(find_image_duplicates(photos, cfg))
    results.extend(find_video_duplicates(videos, cfg))
    results.extend(find_audio_duplicates(audios, cfg))
    return results
