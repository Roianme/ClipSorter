"""Combine QC results and duplicate flags into a final bucket.

For video: only two buckets — "clean" (usable) or "rejected" (defects).
For photo/audio: clean, review, rejected, burst.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from duplicate import DuplicatePair, format_duplicate_flag
from qc_video import QCLevel, QCResult

Bucket = Literal["clean", "review", "rejected", "burst"]


class ClassifierResult(TypedDict):
    bucket: Bucket
    reasons: list[str]


def _bucket_from_qc(qc_result: QCResult, detected_type: str = "") -> Bucket:
    """
    Derive bucket from QC results.

    For video: only "clean" (pass) or "rejected".
    For photo/audio: rejected > review > clean.
    """
    if detected_type == "video":
        steady = qc_result.get("steady_shot_check", "rejected")
        if steady == "pass":
            return "clean"
        return "rejected"

    # Photo/audio: original multi-level logic
    checks: list[QCLevel] = [
        qc_result.get("duration_check", "pass"),
        qc_result.get("blur_check", "pass"),
        qc_result.get("content_check", "pass"),
        qc_result.get("saturation_check", "pass"),
        qc_result.get("entropy_check", "pass"),
        qc_result.get("exposure_check", "pass"),
        qc_result.get("shake_check", "pass"),
    ]
    if "rejected" in checks:
        return "rejected"
    if "review" in checks:
        return "review"
    return "clean"


def _duplicate_flags(file_path: str | Path, duplicate_pairs: list[DuplicatePair]) -> list[str]:
    resolved = str(Path(file_path).resolve())
    flags: list[str] = []
    for pair in duplicate_pairs:
        file_a = str(Path(pair["file_a"]).resolve())
        file_b = str(Path(pair["file_b"]).resolve())
        if resolved in (file_a, file_b):
            flags.append(format_duplicate_flag(pair, resolved))
    return flags


def _is_in_burst(file_path: str | Path, burst_groups: list[dict[str, Any]] | None) -> bool:
    if not burst_groups:
        return False
    resolved = str(Path(file_path).resolve())
    for group in burst_groups:
        if resolved in group.get("files", []):
            return True
    return False


def classify_file(
    qc_result: QCResult,
    duplicate_pairs: list[DuplicatePair],
    file_path: str | Path,
    config: dict[str, Any] | None = None,
    burst_groups: list[dict[str, Any]] | None = None,
    detected_type: str = "",
) -> ClassifierResult:
    """
    Classify one file into clean, review, rejected, or burst.

    For video: only "clean" (usable → usable/videos/) or "rejected" (defects → defects/videos/).
    For photo/audio: full multi-level with bursts and duplicates.

    Duplicate pairs force review unless QC already produced rejected.
    Burst groups take priority over clean/review and duplicate review, but not rejected.
    config is accepted for pipeline consistency; not used in classification logic.
    """
    _ = config

    # Video: simple binary outcome regardless of duplicates/bursts
    if detected_type == "video":
        steady = qc_result.get("steady_shot_check", "rejected")
        reasons = list(qc_result["reasons"])
        if steady == "pass":
            return ClassifierResult(bucket="clean", reasons=reasons)
        return ClassifierResult(bucket="rejected", reasons=reasons)

    # Photo/audio: full logic
    qc_bucket = _bucket_from_qc(qc_result)
    reasons = list(qc_result["reasons"])
    duplicate_reasons = _duplicate_flags(file_path, duplicate_pairs)
    in_burst = _is_in_burst(file_path, burst_groups)

    if qc_bucket == "rejected":
        bucket: Bucket = "rejected"
        if duplicate_reasons:
            reasons.extend(duplicate_reasons)
    elif in_burst:
        if duplicate_reasons:
            reasons.extend(duplicate_reasons)
        bucket = "burst"
    elif duplicate_reasons:
        reasons.extend(duplicate_reasons)
        bucket = "review"
    else:
        bucket = qc_bucket

    return ClassifierResult(bucket=bucket, reasons=reasons)
