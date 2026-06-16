"""Recursive folder scan with content-based file type detection."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict, Optional

import magic

from src import pipeline_shared as ps

logger = logging.getLogger(__name__)

DetectedType = Literal["video", "photo", "audio", "unknown"]


class FileRecord(TypedDict):
    original_path: str
    detected_type: Literal["video", "photo", "audio"]
    extension: str
    filename: str


VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mov",
        ".mxf",
        ".avi",
        ".mkv",
        ".wmv",
        ".mts",
        ".m2ts",
        ".3gp",
        ".flv",
        ".webm",
        ".ts",
        ".vob",
    }
)

PHOTO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".heic",
        ".heif",
        ".arw",
        ".cr2",
        ".cr3",
        ".nef",
        ".orf",
        ".raf",
        ".dng",
        ".rw2",
    }
)

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".wav",
        ".aac",
        ".m4a",
        ".flac",
        ".ogg",
        ".wma",
        ".aiff",
        ".opus",
    }
)

IGNORED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".txt",
        ".xml",
        ".zip",
        ".exe",
        ".lnk",
    }
)

SUPPORTED_EXTENSIONS: frozenset[str] = (
    VIDEO_EXTENSIONS | PHOTO_EXTENSIONS | AUDIO_EXTENSIONS
)

# MIME types that do not follow image/*, video/*, or audio/* prefixes.
_EXTRA_MIME_TYPES: dict[str, DetectedType] = {
    "application/mp4": "video",
    "application/mxf": "video",
    "application/x-matroska": "video",
    "application/ogg": "audio",
    "application/x-flac": "audio",
    "application/quicktime": "video",
    "video/quicktime": "video",
}

_INCONCLUSIVE_MIMES: frozenset[str] = frozenset(
    {
        "application/octet-stream",
        "binary/octet-stream",
    }
)


def _normalize_extension(path: Path) -> str:
    return path.suffix.lower()


def _extension_type(extension: str) -> DetectedType:
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in PHOTO_EXTENSIONS:
        return "photo"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


def _mime_to_type(mime: str) -> DetectedType:
    normalized = mime.split(";")[0].strip().lower()
    if not normalized:
        return "unknown"

    if normalized in _EXTRA_MIME_TYPES:
        return _EXTRA_MIME_TYPES[normalized]

    if normalized.startswith("video/"):
        return "video"
    if normalized.startswith("audio/"):
        return "audio"
    if normalized.startswith("image/"):
        return "photo"

    return "unknown"


def _detect_mime(path: Path) -> str | None:
    try:
        return magic.from_file(str(path), mime=True)
    except Exception as exc:
        logger.warning("Could not read file type for %s: %s", path, exc)
        return None


def classify_file(path: Path) -> DetectedType:
    """
    Classify a file using libmagic, with extension fallback when
    magic is inconclusive or unknown.
    """
    extension = _normalize_extension(path)

    if extension in IGNORED_EXTENSIONS:
        return "unknown"

    mime = _detect_mime(path)
    if mime:
        detected = _mime_to_type(mime)
        if detected != "unknown":
            # Special case: application/mp4 could be audio (m4a)
            normalized = mime.split(";")[0].strip().lower()
            if normalized == "application/mp4":
                return _extension_type(extension)
            return detected

        normalized = mime.split(";")[0].strip().lower()
        # For ambiguous or unknown MIME types, fall back to extension
        if normalized in _INCONCLUSIVE_MIMES or detected == "unknown":
            return _extension_type(extension)

        return "unknown"

    # No MIME detected, rely entirely on extension
    return _extension_type(extension)


def _build_record(path: Path, detected_type: Literal["video", "photo", "audio"]) -> FileRecord:
    return FileRecord(
        original_path=str(path.resolve()),
        detected_type=detected_type,
        extension=_normalize_extension(path),
        filename=path.name,
    )


def scan_folder(
    target_folder: Path | str,
    progress_callback: Callable[[str], None] | None = None,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> list[FileRecord]:
    """
    Recursively scan target_folder (or a single file) and return supported media FileRecords.

    Unknown or unsupported files are skipped and logged.
    """
    ps.check_cancelled(cancel_token)
    root = Path(target_folder)
    if not root.exists():
        raise FileNotFoundError(f"Target path does not exist: {root}")

    # Support single file input
    if root.is_file():
        detected = classify_file(root)
        if detected != "unknown":
            return [_build_record(root, detected)]
        return []

    if not root.is_dir():
        raise NotADirectoryError(f"Target path is neither a file nor a directory: {root}")

    records: list[FileRecord] = []
    total_files = sum(len(filenames) for _, _, filenames in os.walk(root))
    processed_files = 0

    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            ps.check_cancelled(cancel_token)
            path = Path(dirpath) / name
            processed_files += 1
            if progress_callback is not None:
                progress_callback(f"__PROGRESS__:{processed_files}/{total_files}")

            if not path.is_file():
                continue

            extension = _normalize_extension(path)
            detected = classify_file(path)

            if detected == "unknown":
                reason = (
                    f"ignored extension {extension}"
                    if extension in IGNORED_EXTENSIONS
                    else "unsupported or unrecognized type"
                )
                logger.info("Skipping %s (%s)", path, reason)
                continue

            records.append(_build_record(path, detected))

    records.sort(key=lambda record: record["original_path"])
    return records
