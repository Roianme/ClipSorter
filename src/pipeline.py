"""Unified media sorting pipeline for photo, video, and audio."""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pipeline_shared import PipelineProgressCallback

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
import pipeline_shared as ps

logger = logging.getLogger(__name__)


class PipelineConfig:
    """Configuration for media-specific pipeline behavior."""

    def __init__(
        self,
        media_type: str,
        qc_function: Callable,
        enable_burst: bool = False,
    ):
        """
        Initialize pipeline configuration.
        
        Args:
            media_type: "photo", "video", or "audio"
            qc_function: Function to run QC checks
            enable_burst: Whether to detect and handle burst groups
        """
        self.media_type = media_type
        self.qc_function = qc_function
        self.enable_burst = enable_burst
        self.canonical_extension = {
            "photo": ".jpg",
            "video": ".mp4",
            "audio": ".mp3",
        }.get(media_type, ".jpg")


def run_media_pipeline(
    target_folder: Path,
    config_path: Path | None,
    verbose: bool,
    pipeline_config: PipelineConfig,
    progress_callback: PipelineProgressCallback | None = None,
) -> int:
    """Run media sorting pipeline for a specific media type."""
    ps.configure_logging(verbose)

    source_folder = target_folder.resolve()
    config = config_loader.load_config(config_path)
    work_dir = converter.get_work_dir()
    media_type = pipeline_config.media_type

    print(f"ClipSorter v1.0 - {media_type.upper()}")
    print(f"Source: {source_folder}")

    # Scan for media type
    ps.emit_progress_stage(progress_callback, "Scanning files...")
    supported_records, unsupported_entries = ps.scan_source_folder(
        source_folder,
        media_types=[media_type],
        progress_callback=progress_callback,
    )
    total_files_found = sum(1 for path in source_folder.rglob("*") if path.is_file())
    files_processed = len(supported_records)
    files_skipped = len(unsupported_entries)

    output_root = mover.setup_output_folder(
        source_folder, media_types=[media_type], include_burst=pipeline_config.enable_burst
    )
    print(f"Output: {output_root}")

    print(ps.summary_text(total_files_found, files_processed, files_skipped))

    if tqdm is not None:
        for _ in ps.progress([None], desc="Scanning files", total=1, unit="stage"):
            pass

    # Convert files
    ps.emit_progress_stage(progress_callback, "Converting formats...")
    converted_records: list[converter.ConvertedFileRecord] = []
    print("Converting formats...", end=" ", flush=True)

    max_workers = config.get("conversion_parallel_workers", 4)
    if max_workers < 1:
        max_workers = 1

    total_conversions = len(supported_records)
    if tqdm is not None:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for record in supported_records:
                future = executor.submit(
                    converter.convert_file, record, config, work_dir=work_dir
                )
                futures[future] = record

            completed = 0
            with ps.progress(
                total=total_conversions,
                desc="Converting formats",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            ) as pbar:
                for future in as_completed(futures):
                    record = futures[future]
                    try:
                        converted_records.append(future.result())
                    except Exception as exc:
                        logger.exception("Conversion failed for %s", record["original_path"])
                        unsupported_entries.append(
                            {
                                "bucket": "skipped",
                                "final_path": ps.relative_path(
                                    source_folder, Path(record["original_path"])
                                ),
                                "original_path": ps.relative_path(
                                    source_folder, Path(record["original_path"])
                                ),
                                "reason": str(exc),
                            }
                        )
                    completed += 1
                    pbar.update(1)
                    ps.emit_progress_value(progress_callback, completed, total_conversions)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for record in supported_records:
                future = executor.submit(
                    converter.convert_file, record, config, work_dir=work_dir
                )
                futures[future] = record

            completed = 0
            for future in as_completed(futures):
                record = futures[future]
                try:
                    converted_records.append(future.result())
                except Exception as exc:
                    logger.exception("Conversion failed for %s", record["original_path"])
                    unsupported_entries.append(
                        {
                            "bucket": "skipped",
                            "final_path": ps.relative_path(
                                source_folder, Path(record["original_path"])
                            ),
                            "original_path": ps.relative_path(
                                source_folder, Path(record["original_path"])
                            ),
                            "reason": str(exc),
                        }
                    )
                completed += 1
                ps.emit_progress_value(progress_callback, completed, total_conversions)
    print("Done")

    # Run QC checks
    ps.emit_progress_stage(progress_callback, "Running QC checks...")
    qc_results: dict[str, dict[str, Any]] = {}
    print("Running QC checks...", end=" ", flush=True)

    qc_workers = config.get("qc_parallel_workers", 2)
    if qc_workers < 1:
        qc_workers = 1

    qc_functions = {media_type: pipeline_config.qc_function}

    total_qc = len(converted_records)
    if tqdm is not None:
        with ThreadPoolExecutor(max_workers=qc_workers) as executor:
            futures = {
                executor.submit(ps.run_qc_check_wrapper, record, config, qc_functions): record
                for record in converted_records
            }
            completed = 0
            with ps.progress(
                total=total_qc,
                desc="Running QC checks",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            ) as pbar:
                for future in as_completed(futures):
                    path, result = future.result()
                    if path:
                        qc_results[path] = result
                    completed += 1
                    pbar.update(1)
                    ps.emit_progress_value(progress_callback, completed, total_qc)
    else:
        with ThreadPoolExecutor(max_workers=qc_workers) as executor:
            futures = {
                executor.submit(ps.run_qc_check_wrapper, record, config, qc_functions): record
                for record in converted_records
            }
            completed = 0
            for future in as_completed(futures):
                path, result = future.result()
                if path:
                    qc_results[path] = result
                completed += 1
                ps.emit_progress_value(progress_callback, completed, total_qc)
    print("Done")

    # Get media paths
    media_paths = [r["converted_path"] for r in converted_records if r.get("converted_path")]

    # Detect burst groups (photo-only)
    burst_groups: list[dict[str, Any]] = []
    if pipeline_config.enable_burst:
        print("Detecting burst groups...", end=" ")
        if tqdm is not None:
            with ps.progress(
                total=1, desc="Detecting burst groups", dynamic_ncols=True, ncols=80, ascii=True
            ) as burst_bar:
                try:
                    burst_groups = duplicate.find_burst_groups(media_paths, config)
                except Exception:
                    logger.exception("Burst detection failed")
                burst_bar.update(1)
        else:
            try:
                burst_groups = duplicate.find_burst_groups(media_paths, config)
            except Exception:
                logger.exception("Burst detection failed")
        print(f"Done — {len(burst_groups)} burst groups found")

    selected_burst_representatives = ps.choose_best_burst_representatives(burst_groups, qc_results)

    # Detect duplicates
    ps.emit_progress_stage(progress_callback, "Detecting duplicates...")
    duplicate_pairs = []
    print("Detecting duplicates...", end=" ")
    photo_paths = media_paths if media_type == "photo" else []
    video_paths = media_paths if media_type == "video" else []
    audio_paths = media_paths if media_type == "audio" else []

    if tqdm is not None:
        with ps.progress(
            total=1, desc="Detecting duplicates", dynamic_ncols=True, ncols=80, ascii=True
        ) as dup_bar:
            try:
                duplicate_pairs = duplicate.find_duplicates(
                    photo_paths=photo_paths,
                    video_paths=video_paths,
                    audio_paths=audio_paths,
                    config=config,
                )
            except Exception:
                logger.exception("Duplicate detection failed")
            dup_bar.update(1)
    else:
        try:
            duplicate_pairs = duplicate.find_duplicates(
                photo_paths=photo_paths,
                video_paths=video_paths,
                audio_paths=audio_paths,
                config=config,
            )
        except Exception:
            logger.exception("Duplicate detection failed")
    ps.emit_progress_value(progress_callback, 1, 1)
    print(f"Done — {len(duplicate_pairs)} duplicate pairs found")

    # Classify files
    ps.emit_progress_stage(progress_callback, "Classifying files...")
    classifications: dict[str, classifier.ClassifierResult] = {}
    print("Classifying files...", end=" ", flush=True)

    total_classifications = len(converted_records)
    if tqdm is not None:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    ps.run_classifier_check_wrapper, record, qc_results, duplicate_pairs, burst_groups, config
                ): record
                for record in converted_records
            }
            completed = 0
            with ps.progress(
                total=total_classifications,
                desc="Classifying files",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            ) as pbar:
                for future in as_completed(futures):
                    path, result = future.result()
                    if path:
                        classifications[path] = result
                    completed += 1
                    pbar.update(1)
                    ps.emit_progress_value(progress_callback, completed, total_classifications)
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    ps.run_classifier_check_wrapper, record, qc_results, duplicate_pairs, burst_groups, config
                ): record
                for record in converted_records
            }
            completed = 0
            for future in as_completed(futures):
                path, result = future.result()
                if path:
                    classifications[path] = result
                completed += 1
                ps.emit_progress_value(progress_callback, completed, total_classifications)
    print("Done")

    # Move files
    ps.emit_progress_stage(progress_callback, "Moving files...")
    print("Moving files...", end=" ")
    moved_paths: dict[str, str] = {}
    file_sequence_number = 0
    move_records = [r for r in converted_records if r.get("converted_path") and not r.get("skipped")]
    total_moves = len(move_records)
    move_completed = 0
    if tqdm is not None:
        mv_iter = ps.progress(
            converted_records, desc="Moving files", unit="file", dynamic_ncols=True, ncols=80, ascii=True
        )
        for record in mv_iter:
            converted_path = record.get("converted_path")
            if not converted_path or record.get("skipped"):
                mv_iter.set_description("Moving skipped")
                move_completed += 1
                ps.emit_progress_value(progress_callback, move_completed, total_moves)
                continue
            classification = classifications.get(converted_path)
            if classification is None:
                move_completed += 1
                ps.emit_progress_value(progress_callback, move_completed, total_moves)
                continue
            try:
                if classification["bucket"] == "burst" and pipeline_config.enable_burst:
                    if str(Path(converted_path).resolve()) in selected_burst_representatives:
                        qc_res = qc_results.get(
                            converted_path,
                            {
                                "duration_check": "pass",
                                "blur_check": "pass",
                                "exposure_check": "pass",
                                "shake_check": "pass",
                                "reasons": [],
                            },
                        )
                        try:
                            move_bucket = classifier._bucket_from_qc(qc_res, detected_type="photo")
                        except Exception:
                            move_bucket = "clean"
                        mv_iter.set_description(
                            f"Moving burst representative {Path(converted_path).name} -> {move_bucket}"
                        )
                    else:
                        move_bucket = "burst"
                        mv_iter.set_description(f"Moving burst member {Path(converted_path).name} -> burst")
                else:
                    move_bucket = classification["bucket"]
                    mv_iter.set_description(f"Moving {Path(converted_path).name}")
                file_sequence_number += 1
                suffix = Path(converted_path).suffix
                new_filename = f"{source_folder.name}_{media_type}_{file_sequence_number:04d}{suffix}"
                destination = mover.move_file(
                    converted_path,
                    move_bucket,
                    media_type,
                    output_root,
                    new_filename=new_filename,
                )
                moved_paths[converted_path] = str(destination.relative_to(output_root).as_posix())
            except Exception:
                logger.exception("Moving failed for %s", converted_path)
            finally:
                move_completed += 1
                ps.emit_progress_value(progress_callback, move_completed, total_moves)
    else:
        for record in converted_records:
            converted_path = record.get("converted_path")
            if not converted_path or record.get("skipped"):
                move_completed += 1
                ps.emit_progress_value(progress_callback, move_completed, total_moves)
                continue
            classification = classifications.get(converted_path)
            if classification is None:
                move_completed += 1
                ps.emit_progress_value(progress_callback, move_completed, total_moves)
                continue
            try:
                if classification["bucket"] == "burst" and pipeline_config.enable_burst:
                    if str(Path(converted_path).resolve()) in selected_burst_representatives:
                        qc_res = qc_results.get(
                            converted_path,
                            {
                                "duration_check": "pass",
                                "blur_check": "pass",
                                "exposure_check": "pass",
                                "shake_check": "pass",
                                "reasons": [],
                            },
                        )
                        try:
                            move_bucket = classifier._bucket_from_qc(qc_res, detected_type="photo")
                        except Exception:
                            move_bucket = "clean"
                    else:
                        move_bucket = "burst"
                else:
                    move_bucket = classification["bucket"]
                file_sequence_number += 1
                suffix = Path(converted_path).suffix
                new_filename = f"{source_folder.name}_{media_type}_{file_sequence_number:04d}{suffix}"
                destination = mover.move_file(
                    converted_path,
                    move_bucket,
                    media_type,
                    output_root,
                    new_filename=new_filename,
                )
                moved_paths[converted_path] = str(destination.relative_to(output_root).as_posix())
            except Exception:
                logger.exception("Moving failed for %s", converted_path)
    print("Done")

    # Build report
    report_data = {
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_folder": str(source_folder),
        "output_folder": str(output_root),
        "total_files_found": total_files_found,
        "files_processed": files_processed,
        "files_skipped": files_skipped,
        "skipped_note": "unsupported type" if files_skipped else "",
        "media_type": media_type,
        "converted_counts": {
            pipeline_config.canonical_extension.lstrip("."): sum(
                1
                for r in converted_records
                if r.get("converted_path")
                and Path(r["converted_path"]).suffix.lower() == pipeline_config.canonical_extension
            ),
        },
        "results": {
            "review": sum(1 for final_path in moved_paths.values() if final_path.startswith("review/")),
            "defects": sum(1 for final_path in moved_paths.values() if final_path.startswith("defects/")),
        },
        "entries": ps.build_report_entries(
            source_folder,
            output_root,
            converted_records,
            qc_results,
            classifications,
            unsupported_entries,
            moved_paths,
        ),
    }

    ps.emit_progress_stage(progress_callback, "Writing report...")
    ps.emit_progress_value(progress_callback, 0, 1)
    print("Writing report...", end=" ")
    if tqdm is not None:
        with ps.progress(
            total=1, desc="Writing report", dynamic_ncols=True, ncols=80, ascii=True
        ) as rep_bar:
            report_path = reporter.write_report(output_root, report_data)
            rep_bar.update(1)
    else:
        report_path = reporter.write_report(output_root, report_data)
    print("Done")

    print("")
    print("=" * 40)
    print(f"{media_type.upper()} SORTING DONE")
    print(f"  Review:    {report_data['results']['review']} files")
    print(f"  Defects:   {report_data['results']['defects']} files")
    print(f"Report saved to: {report_path}")
    print("=" * 40)

    return 0
