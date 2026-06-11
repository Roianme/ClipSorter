"""Shared pipeline utilities for media sorting."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Literal, TextIO, Optional

Bucket = Literal["clean", "review", "rejected", "burst"]

PipelineProgressCallback = Callable[[str], None]


class PipelineCancelledError(Exception):
    """Raised when the pipeline is cancelled by the user."""
    pass


class CancellationToken:
    """
    Thread-safe token used to signal cancellation to the pipeline.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Trigger cancellation."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been triggered."""
        return self._event.is_set()


def check_cancelled(token: Optional[CancellationToken]) -> None:
    """Raise PipelineCancelledError if the token is set."""
    if token is not None and token.is_cancelled():
        raise PipelineCancelledError("Operation cancelled by user")


ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None

import classifier
import config_loader
import converter
import duplicate
import mover
import reporter
import scanner

logger = logging.getLogger(__name__)


class JsonEmitter:
    """
    Emits structured JSON Lines (one JSON object per line) to a stream.

    Designed for the CLI's ``--json`` flag, where all pipeline status,
    progress, errors, and the final summary are output as parseable JSON.
    """

    def __init__(self, stream: TextIO = sys.stdout) -> None:
        self._stream = stream
        self._closed = False

    def emit_stage(self, stage_name: str) -> None:
        """Emit a stage-change event."""
        self._write({"event": "stage", "name": stage_name})

    def emit_progress(self, current: int, total: int, stage: str | None = None) -> None:
        """Emit a numeric progress update."""
        obj: dict[str, Any] = {"event": "progress", "current": current, "total": total}
        if stage is not None:
            obj["stage"] = stage
        self._write(obj)

    def emit_file_done(self, file_path: str, result: str, **kwargs: Any) -> None:
        """Emit a per-file completion event."""
        obj = {"event": "file_done", "file": file_path, "result": result}
        obj.update(kwargs)
        self._write(obj)

    def emit_error(self, code: str, message: str, file: str | None = None) -> None:
        """Emit an error event."""
        obj: dict[str, Any] = {"event": "error", "code": code, "message": message}
        if file is not None:
            obj["file"] = file
        self._write(obj)

    def emit_summary(self, report_data: dict[str, Any]) -> None:
        """Emit the final summary (last line of output)."""
        self._write({"event": "summary", "report": report_data})

    def close(self) -> None:
        """Flush and close the emitter."""
        if not self._closed:
            self._stream.flush()
            self._closed = True

    def _write(self, obj: dict[str, Any]) -> None:
        """Write a single JSON line to the stream."""
        if self._closed or self._stream is None:
            return
        self._stream.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self._stream.flush()


def configure_logging(verbose: bool) -> None:
    """Configure logging for the pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers = []
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
        
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def progress(iterable, **kwargs):
    """Wrapper for tqdm progress bar. Safe for GUI/frozen environments."""
    # Disable tqdm if:
    # 1. It's not installed
    # 2. We are in GUI mode (explicit override)
    # 3. sys.stderr is None (windowed EXE)
    # 4. sys.stderr is not a TTY (prevents popup windows in some environments)
    if (tqdm is None or 
        os.environ.get("CLIPSORTER_GUI_MODE") == "1" or
        sys.stderr is None or 
        not getattr(sys.stderr, 'isatty', lambda: False)()):
        return iterable
    return tqdm(iterable, **kwargs)


def emit_progress_stage(
    progress_callback: PipelineProgressCallback | None,
    stage: str,
) -> None:
    """Emit a stage update for GUI consumers."""
    if progress_callback is None:
        return
    progress_callback(f"__STAGE__:{stage}")


def emit_progress_value(
    progress_callback: PipelineProgressCallback | None,
    current: int,
    total: int,
) -> None:
    """Emit a numeric progress update for GUI consumers."""
    if progress_callback is None:
        return
    progress_callback(f"__PROGRESS__:{current}/{total}")


def relative_path(root: Path, path: Path) -> str:
    """Get relative path as string."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return f"/{rel.as_posix()}"


def scan_source_folder(
    source_folder: Path,
    media_types: list[str] | None = None,
    progress_callback: PipelineProgressCallback | None = None,
) -> tuple[list[scanner.FileRecord], list[dict[str, Any]]]:
    """Scan source folder (or file) and filter by media types."""
    all_records = scanner.scan_folder(source_folder, progress_callback=progress_callback)
    
    # Filter by media types if specified
    if media_types is not None:
        supported = [r for r in all_records if r["detected_type"] in media_types]
    else:
        supported = all_records
    
    supported_set = {Path(record["original_path"]).resolve() for record in supported}
    skipped_entries: list[dict[str, Any]] = []

    # Handle single file or directory for skipped/unsupported check
    if source_folder.is_file():
        if source_folder.resolve() not in supported_set:
            skipped_entries.append(
                {
                    "bucket": "skipped",
                    "final_path": relative_path(source_folder.parent, source_folder),
                    "original_path": relative_path(source_folder.parent, source_folder),
                    "reason": "Unsupported or non-matching file type",
                }
            )
    else:
        for path in sorted(source_folder.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in supported_set:
                continue
            skipped_entries.append(
                {
                    "bucket": "skipped",
                    "final_path": relative_path(source_folder, path),
                    "original_path": relative_path(source_folder, path),
                    "reason": "Unsupported or non-matching file type",
                }
            )

    return supported, skipped_entries


def summary_text(total: int, processed: int, skipped: int) -> str:
    """Format summary text."""
    return f"Scanning files...        {total} files found ({processed} supported, {skipped} skipped)"


def format_metadata(qc_result: dict[str, Any], detected_type: str) -> dict[str, str]:
    """Format QC metadata for reporting."""
    metadata: dict[str, str] = {}
    duration_status = qc_result["duration_check"].upper()
    if duration_status != "PASS":
        duration_reason = next(
            (msg for msg in qc_result["reasons"] if msg.lower().startswith("duration")),
            None,
        )
        metadata["Duration"] = f"{duration_status} ({duration_reason})" if duration_reason else duration_status
    else:
        metadata["Duration"] = "PASS"

    if detected_type == "video":
        steady_status = qc_result.get("steady_shot_check", "rejected").upper()
        reasons = qc_result.get("reasons", [])
        steady_reason = next(
            (msg for msg in reasons if "steady" in msg.lower() or "5-second" in msg.lower() or "window" in msg.lower()),
            None,
        )
        metadata["SteadyShot"] = steady_status if steady_reason is None else f"{steady_status} ({steady_reason})"
    elif detected_type == "photo":
        blur_status = qc_result["blur_check"].upper()
        exposure_status = qc_result["exposure_check"].upper()
        blur_reason = next((msg for msg in qc_result["reasons"] if msg.startswith("Blur:")), None)
        exposure_reason = next(
            (msg for msg in qc_result["reasons"] if msg.startswith("Exposure:")), None
        )
        metadata["Blur"] = blur_status if blur_reason is None else f"{blur_status} ({blur_reason[len('Blur: '):]})"
        metadata["Exposure"] = (
            exposure_status
            if exposure_reason is None
            else f"{exposure_status} ({exposure_reason[len('Exposure: '):]})"
        )
    elif detected_type == "audio":
        silence_status = qc_result["exposure_check"].upper()
        silence_reason = next((msg for msg in qc_result["reasons"] if msg.startswith("Silence:")), None)
        metadata["Duration"] = metadata["Duration"]
        metadata["Silence"] = silence_status if silence_reason is None else f"{silence_status} ({silence_reason[len('Silence: '):]})"
    return metadata


def score_photo_for_burst(qc_result: dict[str, Any]) -> tuple[int, int, int]:
    """Score photo for burst selection."""
    blur_score = 2 if qc_result.get("blur_check") == "pass" else 1
    exposure_score = 2 if qc_result.get("exposure_check") == "pass" else 1
    reason_penalty = len(qc_result.get("reasons", []))
    return (blur_score, exposure_score, -reason_penalty)


def run_qc_check_wrapper(
    record: converter.ConvertedFileRecord,
    config: dict[str, Any],
    qc_functions: dict[str, Callable],
    sub_progress: converter.SubProgressCallback | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run QC analysis on a single file."""
    converted_path = record.get("converted_path")
    if not converted_path or record.get("skipped"):
        return converted_path or "", {}

    image_array = record.get("image_array")
    detected_type = record["detected_type"]

    try:
        if detected_type not in qc_functions:
            return converted_path, {
                "duration_check": "pass",
                "blur_check": "pass",
                "exposure_check": "pass",
                "shake_check": "pass",
                "reasons": [],
            }

        qc_func = qc_functions[detected_type]
        
        if detected_type == "video":
            return converted_path, qc_func(converted_path, config, sub_progress=sub_progress)
        elif detected_type == "photo":
            if sub_progress:
                sub_progress(0.5) # Generic mid-point for photos
            if image_array is not None:
                res = qc_func(config=config, frame=image_array)
            else:
                res = qc_func(converted_path, config)
            if sub_progress:
                sub_progress(1.0)
            return converted_path, res
        elif detected_type == "audio":
            if sub_progress:
                sub_progress(0.5)
            res = qc_func(converted_path, config)
            if sub_progress:
                sub_progress(1.0)
            return converted_path, res
        else:
            return converted_path, {
                "duration_check": "pass",
                "blur_check": "pass",
                "exposure_check": "pass",
                "shake_check": "pass",
                "reasons": [],
            }
    except Exception:
        logger.exception("QC failed for %s", converted_path)
        if detected_type == "video":
            return converted_path, {
                "duration_check": "rejected",
                "steady_shot_check": "rejected",
                "reasons": ["QC analysis failed"],
            }
        return converted_path, {
            "duration_check": "review",
            "blur_check": "review",
            "exposure_check": "review",
            "shake_check": "review",
            "reasons": ["QC analysis failed"],
        }


def run_classifier_check_wrapper(
    record: converter.ConvertedFileRecord,
    qc_results: dict[str, dict[str, Any]],
    duplicate_pairs: list[Any],
    burst_groups: list[Any],
    config: dict[str, Any],
) -> tuple[str, classifier.ClassifierResult]:
    """Classify a single file."""
    converted_path = record.get("converted_path")
    if not converted_path or record.get("skipped"):
        return converted_path or "", {"bucket": "skipped", "reasons": []}

    qc_result = qc_results.get(converted_path)
    if qc_result is None:
        detected_type = record.get("detected_type", "")
        if detected_type == "video":
            qc_result = {
                "duration_check": "pass",
                "steady_shot_check": "pass",
                "reasons": [],
            }
        else:
            qc_result = {
                "duration_check": "pass",
                "blur_check": "pass",
                "exposure_check": "pass",
                "shake_check": "pass",
                "reasons": [],
            }

    detected_type = record.get("detected_type", "")
    try:
        return converted_path, classifier.classify_file(
            qc_result,
            duplicate_pairs,
            converted_path,
            config=config,
            burst_groups=burst_groups,
            detected_type=detected_type,
        )
    except Exception:
        logger.exception("Classification failed for %s", converted_path)
        fallback_bucket = "rejected" if detected_type == "video" else "review"
        return converted_path, {"bucket": fallback_bucket, "reasons": ["Classification failed"]}


def choose_best_burst_representatives(
    burst_groups: list[dict[str, Any]],
    qc_results: dict[str, dict[str, Any]],
) -> set[str]:
    """Choose best burst representatives based on QC scores."""
    selected: set[str] = set()
    for group in burst_groups:
        best_file = None
        best_score: tuple[int, int, int] | None = None
        for raw_path in group.get("files", []):
            path = str(Path(raw_path).resolve())
            qc_result = qc_results.get(
                path,
                {
                    "blur_check": "pass",
                    "exposure_check": "pass",
                    "reasons": [],
                },
            )
            score = score_photo_for_burst(qc_result)
            if best_score is None or score > best_score or (score == best_score and Path(path).name < Path(best_file).name):
                best_score = score
                best_file = path
        if best_file:
            selected.add(best_file)
    return selected


def converted_from_text(record: scanner.FileRecord) -> str:
    """Get conversion status text."""
    extension = record["extension"].lower()
    return f"Original: {extension}"


def build_report_entries(
    source_folder: Path,
    output_folder: Path,
    converted_records: list[converter.ConvertedFileRecord],
    qc_results: dict[str, dict[str, Any]],
    classifications: dict[str, classifier.ClassifierResult],
    skipped_entries: list[dict[str, Any]],
    moved_paths: dict[str, str],
) -> list[dict[str, Any]]:
    """Build report entries from pipeline results."""
    entries: list[dict[str, Any]] = []

    for record in converted_records:
        original = Path(record["original_path"])
        converted_path = record.get("converted_path")
        final_path = moved_paths.get(str(Path(converted_path or "")))
        if final_path is None:
            entries.append(
                {
                    "bucket": "skipped",
                    "final_path": relative_path(source_folder, original),
                    "original_path": relative_path(source_folder, original),
                    "reason": record.get("reason", "Conversion failed or skipped"),
                }
            )
            continue

        qc_result = qc_results.get(str(Path(record["converted_path"])))
        classification = classifications.get(str(Path(record["converted_path"])))
        if record["detected_type"] == "video":
            default_qc = {
                "duration_check": "pass",
                "steady_shot_check": "pass",
                "reasons": [],
            }
        else:
            default_qc = {
                "duration_check": "pass",
                "blur_check": "pass",
                "exposure_check": "pass",
                "shake_check": "pass",
                "reasons": [],
            }
        metadata = format_metadata(qc_result if qc_result is not None else default_qc, record["detected_type"])

        entries.append(
            {
                "bucket": classification["bucket"] if classification is not None else "clean",
                "final_path": final_path,
                "original_path": relative_path(source_folder, original),
                "converted_from": converted_from_text(record),
                "metadata": metadata,
                "flags": classification["reasons"] if classification is not None else [],
            }
        )

    entries.extend(skipped_entries)
    return entries
