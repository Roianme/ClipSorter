"""Create output folder structure and move converted files from temp work dir."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.pipeline_shared import Bucket
import pipeline_shared as ps

logger = logging.getLogger(__name__)

BUCKETS: tuple[Bucket, ...] = ("clean", "review", "rejected", "burst")
OUTPUT_BUCKETS: tuple[str, ...] = ("review", "defects")
BUCKET_TO_OUTPUT: dict[Bucket, str] = {
    "clean": "review",
    "review": "review",
    "burst": "review",
    "rejected": "defects",
}

# Video only uses review/ and defects/ (no review bucket-specific folder, no burst)
VIDEO_BUCKET_TO_OUTPUT: dict[Bucket, str] = {
    "clean": "review",
    "rejected": "defects",
}

TYPE_SUBFOLDERS: dict[str, str] = {
    "video": "videos",
    "photo": "photos",
    "audio": "audio",
}


def _type_subfolder(detected_type: str) -> str:
    try:
        return TYPE_SUBFOLDERS[detected_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported detected_type for move: {detected_type}") from exc


def _create_bucket_tree(output_folder: Path, media_types: list[str] | None = None, include_burst: bool = False) -> None:
    """Create output folder tree.

    If `media_types` is provided, only create subfolders for those types.
    If `include_burst` is True and photos are included, create a dedicated
    `review/burst/<photo_subfolder>` location for burst members.
    """
    # If a single media type is requested, create top-level bucket folders
    # (e.g., review/, defects/) to avoid a redundant per-type subfolder.
    if media_types is not None and len(media_types) == 1:
        for bucket in OUTPUT_BUCKETS:
            (output_folder / bucket).mkdir(parents=True, exist_ok=True)

        # Create burst folder directly under review/ when requested for photos
        if include_burst and media_types[0] == "photo":
            (output_folder / "review" / "burst").mkdir(parents=True, exist_ok=True)
        return

    # Default behaviour: create per-type subfolders under each bucket
    types = TYPE_SUBFOLDERS.keys() if media_types is None else media_types
    for bucket in OUTPUT_BUCKETS:
        for t in types:
            subfolder = TYPE_SUBFOLDERS.get(t)
            if subfolder is None:
                continue
            (output_folder / bucket / subfolder).mkdir(parents=True, exist_ok=True)

    # Create a dedicated review/burst/<type> location for photos when requested
    if include_burst and (media_types is None or "photo" in media_types):
        photo_sub = TYPE_SUBFOLDERS.get("photo")
        if photo_sub:
            (output_folder / "review" / "burst" / photo_sub).mkdir(parents=True, exist_ok=True)


def setup_output_folder(target_folder: Path | str, media_types: list[str] | None = None, include_burst: bool = False, dry_run: bool = False) -> Path:
    """
    Create sibling output folder TargetFolder_sorted/ with bucket/type subfolders.

    If that path already exists, append a timestamp suffix per Section 13.
    """
    target = Path(target_folder).resolve()
    # Use stem for files to avoid extension in folder name (e.g. video_sorted/ instead of video.mp4_sorted/)
    name_to_use = target.stem if target.is_file() else target.name
    base_name = f"{name_to_use}_sorted"
    parent = target.parent
    output_folder = parent / base_name

    if output_folder.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_folder = parent / f"{base_name}_{stamp}"
        logger.warning("Output folder exists; using %s", output_folder)

    if not dry_run:
        output_folder.mkdir(parents=True, exist_ok=True)
        _create_bucket_tree(output_folder, media_types=media_types, include_burst=include_burst)
    return output_folder.resolve()


def _allocate_destination(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate

    path = Path(filename)
    counter = 1
    while True:
        candidate = dest_dir / f"{path.stem}_{counter}{path.suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_file(
    converted_path: Path | str,
    bucket: Bucket,
    detected_type: str,
    output_folder: Path | str,
    new_filename: str | None = None,
    dry_run: bool = False,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> Path:
    """
    Move a converted file from temp work dir into bucket/type subfolder.

    Video only uses review/ and defects/ (2 folders).
    Photo/audio output also uses only review/ and defects/ top-level folders.
    Never overwrites an existing file; appends _1, _2, ... on collision.
    If new_filename is provided, use it for the destination file name.
    Does not modify the original TargetFolder.
    """
    ps.check_cancelled(cancel_token)
    source = Path(converted_path)
    # In dry_run, the converted_path is simulated and might not exist on disk
    if not dry_run and not source.is_file():
        raise FileNotFoundError(f"Converted file not found: {source}")

    root = Path(output_folder).resolve()

    # Video: only clean/rejected allowed
    if detected_type == "video":
        if bucket not in ("clean", "rejected"):
            raise ValueError(f"Video only supports clean or rejected buckets, got: {bucket}")
        output_bucket = VIDEO_BUCKET_TO_OUTPUT[bucket]

        # Prefer per-type folder if it exists, otherwise use bucket root
        candidate_type_dir = root / output_bucket / _type_subfolder(detected_type)
        if candidate_type_dir.exists():
            dest_dir = candidate_type_dir
        else:
            dest_dir = root / output_bucket

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
        filename = new_filename if new_filename is not None else source.name
        
        if dry_run:
            # Simple prediction for dry run
            return (dest_dir / filename).resolve()
            
        destination = _allocate_destination(dest_dir, filename)
        shutil.move(str(source), str(destination))
        logger.info("Moved %s -> %s", source, destination)
        return destination.resolve()

    # Photo/audio: full bucket logic
    if bucket not in BUCKETS:
        raise ValueError(f"Invalid bucket: {bucket}")
    if bucket == "burst" and detected_type != "photo":
        raise ValueError("Burst bucket is only supported for photos")

    root = Path(output_folder).resolve()
    output_bucket = BUCKET_TO_OUTPUT[bucket]

    # Prefer per-type folder if present
    candidate_type_dir = root / output_bucket / _type_subfolder(detected_type)
    if candidate_type_dir.exists():
        dest_dir = candidate_type_dir
    else:
        # Special-case burst: prefer review/burst[/<type>] if present
        if bucket == "burst":
            candidate_burst_type_dir = root / "review" / "burst" / _type_subfolder(detected_type)
            if candidate_burst_type_dir.exists():
                dest_dir = candidate_burst_type_dir
            elif (root / "review" / "burst").exists():
                dest_dir = root / "review" / "burst"
            else:
                dest_dir = root / output_bucket
        else:
            # Fallback to bucket root (created for single-type runs) or create per-type
            if (root / output_bucket).exists():
                dest_dir = root / output_bucket
            else:
                dest_dir = root / output_bucket / _type_subfolder(detected_type)

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
    filename = new_filename if new_filename is not None else source.name
    
    if dry_run:
        # Simple prediction for dry run
        return (dest_dir / filename).resolve()
        
    destination = _allocate_destination(dest_dir, filename)
    shutil.move(str(source), str(destination))
    logger.info("Moved %s -> %s", source, destination)
    return destination.resolve()


def manual_move(source: Path, dest_dir: Path) -> Path:
    """Move a file to a specific folder, handling collisions."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = _allocate_destination(dest_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination
