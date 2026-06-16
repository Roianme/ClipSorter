"""Unified media sorting pipeline for photo, video, and audio."""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.pipeline_shared import JsonEmitter, PipelineProgressCallback

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import classifier
import config_loader
import converter
import duplicate
import mover
import reporter
import scanner
import pipeline_shared as ps

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _as_completed_responsive(futures: dict[concurrent.futures.Future, Any], cancel_token: ps.CancellationToken | None):
    """Yield futures as they complete, but check for cancellation frequently."""
    remaining = set(futures.keys())
    while remaining:
        ps.check_cancelled(cancel_token)
        done, _ = concurrent.futures.wait(
            remaining, timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED
        )
        if not done:
            continue
        for f in done:
            remaining.remove(f)
            yield f


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
    json_emitter: JsonEmitter | None = None,
    dry_run: bool = False,
    cancel_token: ps.CancellationToken | None = None,
    # New parameter to allow passing already scanned records
    pre_scanned_records: tuple[list[scanner.FileRecord], list[dict[str, Any]]] | None = None,
) -> int:
    """Run media sorting pipeline for a specific media type."""
    ps.configure_logging(verbose)

    source_folder = target_folder.resolve()
    config = config_loader.load_config(config_path)
    work_dir = converter.get_work_dir()
    media_type = pipeline_config.media_type

    def _j(emitter_method: str, *args: Any, **kwargs: Any) -> None:
        """Helper: call emitter method if emitter is active."""
        if json_emitter is not None:
            getattr(json_emitter, emitter_method)(*args, **kwargs)

    try:
        ps.check_cancelled(cancel_token)
        if json_emitter is None:
            prefix = "DRY RUN: " if dry_run else ""
            print(f"{prefix}ClipSorter v1.0 - {media_type.upper()}")
            print(f"{prefix}Source: {source_folder}")
        else:
            json_emitter.emit_stage(f"ClipSorter v1.0 - {media_type.upper()}")
            json_emitter.emit_file_done(str(source_folder), "source_folder")

        # Scan for media type
        ps.emit_progress_stage(progress_callback, "Scanning files...")
        _j("emit_stage", "Scanning files")
        
        if pre_scanned_records:
            all_supported, all_unsupported = pre_scanned_records
            supported_records = [r for r in all_supported if r["detected_type"] == media_type]
            unsupported_entries = all_unsupported # Simplification
        else:
            supported_records, unsupported_entries = ps.scan_source_folder(
                source_folder,
                media_types=[media_type],
                progress_callback=progress_callback,
            )
            
        if source_folder.is_file():
            total_files_found = 1
        else:
            total_files_found = sum(1 for path in source_folder.rglob("*") if path.is_file())
            
        files_processed = len(supported_records)
        files_skipped = len(unsupported_entries)
        
        # Check if we have anything to do
        if files_processed == 0:
            if json_emitter is None:
                print(f"No {media_type} files found to process.")
            else:
                _j("emit_summary", {"results": {"review": 0, "defects": 0}})
            return 0

        output_root = mover.setup_output_folder(
            source_folder, media_types=[media_type], include_burst=pipeline_config.enable_burst,
            dry_run=dry_run,
        )
        if json_emitter is None:
            prefix = "DRY RUN: " if dry_run else ""
            print(f"{prefix}Output: {output_root}")
            print(ps.summary_text(total_files_found, files_processed, files_skipped))
            
            for _ in ps.progress([None], desc="Scanning files", total=1, unit="stage"):
                pass
        else:
            json_emitter.emit_file_done(str(output_root), "output_folder")

        # --- Progress Helper ---
        def _make_sub_cb(file_record: scanner.FileRecord, total_count: int, completed_count: int):
            def _sub_cb(percent: float):
                # Emit sub-progress event: __SUBPROGRESS__:current_file_index/total_files:percent:filename
                file_name = Path(file_record["original_path"]).name
                if progress_callback:
                    progress_callback(f"__SUBPROGRESS__:{completed_count+1}/{total_count}:{percent:.2f}:{file_name}")
            return _sub_cb

        # Convert files
        ps.check_cancelled(cancel_token)
        ps.emit_progress_stage(progress_callback, "Converting formats...")
        _j("emit_stage", "Converting formats")
        converted_records: list[converter.ConvertedFileRecord] = []
        if json_emitter is None:
            prefix = "DRY RUN: " if dry_run else ""
            print(f"{prefix}Converting formats...", end=" ", flush=True)

        max_workers = config.get("conversion_parallel_workers", 4)
        if max_workers < 1:
            max_workers = 1

        total_conversions = len(supported_records)
        # Using a unified executor logic
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for i, record in enumerate(supported_records):
                sub_cb = _make_sub_cb(record, total_conversions, i)
                future = executor.submit(
                    converter.convert_file, record, config, work_dir=work_dir, dry_run=dry_run,
                    cancel_token=cancel_token, sub_progress=sub_cb
                )
                futures[future] = record

            completed = 0
            # Helper for tqdm/no-tqdm
            progress_iter = ps.progress(
                _as_completed_responsive(futures, cancel_token),
                total=total_conversions,
                desc="Converting formats",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            )
            
            for future in progress_iter:
                ps.check_cancelled(cancel_token)
                record = futures[future]
                try:
                    converted_records.append(future.result())
                except ps.PipelineCancelledError:
                    raise
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
                _j("emit_progress", completed, total_conversions, "Converting formats")
                if dry_run:
                    _j("emit_file_done", record["original_path"], "would_convert")
        if json_emitter is None:
            print("Done")

        # Run QC checks
        ps.emit_progress_stage(progress_callback, "Running QC checks...")
        _j("emit_stage", "Running QC checks")
        qc_results: dict[str, dict[str, Any]] = {}
        if json_emitter is None:
            print("Running QC checks...", end=" ", flush=True)

        qc_workers = config.get("qc_parallel_workers", 2)
        if qc_workers < 1:
            qc_workers = 1

        qc_functions = {media_type: pipeline_config.qc_function}

        total_qc = len(converted_records)
        with ThreadPoolExecutor(max_workers=qc_workers) as executor:
            futures = {}
            for i, record in enumerate(converted_records):
                sub_cb = _make_sub_cb(record, total_qc, i)
                future = executor.submit(ps.run_qc_check_wrapper, record, config, qc_functions, sub_progress=sub_cb, cancel_token=cancel_token)
                futures[future] = record

            completed = 0
            progress_iter = ps.progress(
                _as_completed_responsive(futures, cancel_token),
                total=total_qc,
                desc="Running QC checks",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            )
            
            for future in progress_iter:
                path, result = future.result()
                if path:
                    qc_results[path] = result
                completed += 1
                ps.emit_progress_value(progress_callback, completed, total_qc)
                _j("emit_progress", completed, total_qc, "Running QC checks")
        if json_emitter is None:
            print("Done")

        # Get media paths
        media_paths = [r["converted_path"] for r in converted_records if r.get("converted_path")]

        # Detect burst groups (photo-only)
        burst_groups: list[dict[str, Any]] = []
        if pipeline_config.enable_burst:
            _j("emit_stage", "Detecting burst groups")
            if json_emitter is None:
                print("Detecting burst groups...", end=" ")
            
            try:
                burst_groups = duplicate.find_burst_groups(media_paths, config, cancel_token=cancel_token)
            except Exception:
                logger.exception("Burst detection failed")
            
            if json_emitter is None:
                print(f"Done — {len(burst_groups)} burst groups found")
            else:
                for bg in burst_groups:
                    for f in bg.get("files", []):
                        _j("emit_file_done", f, "burst_group")

        selected_burst_representatives = ps.choose_best_burst_representatives(burst_groups, qc_results)

        # Detect duplicates
        ps.emit_progress_stage(progress_callback, "Detecting duplicates...")
        _j("emit_stage", "Detecting duplicates")
        duplicate_pairs = []
        if json_emitter is None:
            print("Detecting duplicates...", end=" ")
        photo_paths = media_paths if media_type == "photo" else []
        video_paths = media_paths if media_type == "video" else []
        audio_paths = media_paths if media_type == "audio" else []

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
        if json_emitter is None:
            print(f"Done — {len(duplicate_pairs)} duplicate pairs found")

        # Classify files
        ps.emit_progress_stage(progress_callback, "Classifying files...")
        _j("emit_stage", "Classifying files")
        classifications: dict[str, classifier.ClassifierResult] = {}
        if json_emitter is None:
            print("Classifying files...", end=" ", flush=True)

        total_classifications = len(converted_records)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(
                    ps.run_classifier_check_wrapper, record, qc_results, duplicate_pairs, burst_groups, config, cancel_token=cancel_token
                ): record
                for record in converted_records
            }
            completed = 0
            progress_iter = ps.progress(
                _as_completed_responsive(futures, cancel_token),
                total=total_classifications,
                desc="Classifying files",
                unit="file",
                dynamic_ncols=True,
                ncols=100,
                ascii=True,
            )
            
            for future in progress_iter:
                path, result = future.result()
                if path:
                    classifications[path] = result
                completed += 1
                ps.emit_progress_value(progress_callback, completed, total_classifications)
                _j("emit_progress", completed, total_classifications, "Classifying files")
        if json_emitter is None:
            print("Done")

        # Move files
        ps.emit_progress_stage(progress_callback, "Moving files...")
        _j("emit_stage", "Moving files")
        if json_emitter is None:
            print("Moving files...", end=" ")
        moved_paths: dict[str, str] = {}
        file_sequence_number = 0
        
        # Simplified move logic using same iterator structure
        for record in converted_records:
            ps.check_cancelled(cancel_token)
            converted_path = record.get("converted_path")
            if not converted_path or record.get("skipped"):
                continue
            
            classification = classifications.get(converted_path)
            if classification is None:
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
                    dry_run=dry_run,
                    cancel_token=cancel_token
                )
                moved_paths[converted_path] = str(destination.relative_to(output_root).as_posix())
                if dry_run:
                    _j("emit_file_done", converted_path, "would_move", dest=moved_paths[converted_path])
            except ps.PipelineCancelledError:
                raise
            except Exception:
                logger.exception("Moving failed for %s", converted_path)
            
        if json_emitter is None:
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
            "dry_run": dry_run,
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
        _j("emit_stage", "Writing report")
        if json_emitter is None:
            prefix = "DRY RUN: " if dry_run else ""
            print(f"{prefix}Writing report...", end=" ")
        
        report_path = output_root / "_report.txt"
        if not dry_run:
            report_path = reporter.write_report(output_root, report_data)
        
        if json_emitter is None:
            print("Done")

        # Emit summary as final event to callback and JSON mode
        summary_event = {"event": "summary", "report": report_data}
        if progress_callback:
            import json
            progress_callback(f"__SUMMARY__:{json.dumps(report_data)}")
        _j("emit_summary", report_data)

        if json_emitter is None:
            prefix = "DRY RUN: " if dry_run else ""
            print("")
            print("=" * 40)
            print(f"{prefix}{media_type.upper()} SORTING DONE")
            print(f"  Review:    {report_data['results']['review']} files")
            print(f"  Defects:   {report_data['results']['defects']} files")
            if dry_run:
                print(f"  Report would be saved to: {report_path}")
            else:
                print(f"  Report saved to: {report_path}")
            print("=" * 40)

            return 0
            
    except ps.PipelineCancelledError:
        if json_emitter is not None:
            json_emitter.emit_error("CANCELLED", "Operation cancelled by user")
            # Also emit a final cancelled event as per requirement 4
            json_emitter._write({"event": "cancelled"})
        else:
            print("\nSorting cancelled.")
        return 130
