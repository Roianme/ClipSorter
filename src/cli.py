"""CLI module for separate media type sorting."""

from __future__ import annotations

import argparse
import sys
import signal
from pathlib import Path
from typing import Any

from src.pipeline_shared import JsonEmitter
from src.service import MediaPipelineService
from src.version import __version__


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by all subcommands."""
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a custom config.json file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Emit structured JSON Lines output instead of human-readable text",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Simulate the process without moving or converting files",
    )


def _build_base_parser() -> argparse.ArgumentParser:
    """Build base argument parser for all commands."""
    parser = argparse.ArgumentParser(
        prog="ClipSorter",
        description=(
            "Non-destructive media sorting pipeline. Creates organized copies of your "
            "photos, videos, and audio in a sibling folder, isolating defective files "
            "without modifying original data."
        )
    )
    parser.add_argument("--version", action="version", version=f"ClipSorter {__version__}")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
        # Photo command
    photo_parser = subparsers.add_parser("photo", help="Sort photos only")
    photo_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(photo_parser)
    photo_parser.set_defaults(mode="photo")
    
    # Video command
    video_parser = subparsers.add_parser("video", help="Sort videos only")
    video_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(video_parser)
    video_parser.set_defaults(mode="video")
    
    # Audio command
    audio_parser = subparsers.add_parser("audio", help="Sort audio files only")
    audio_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(audio_parser)
    audio_parser.set_defaults(mode="audio")
    
    # All command
    all_parser = subparsers.add_parser("all", help="Sort all media types (photo, video, audio)")
    all_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(all_parser)
    all_parser.set_defaults(mode="all")
    
    return parser


def _run_pipeline(args: Any) -> int:
    """Run pipeline via MediaPipelineService."""
    target_folder = args.target_folder
    
    if args.json:
        emitter = JsonEmitter(sys.stdout)
        
        def callback(event: dict[str, Any]) -> None:
            # Simple adaptation for JsonEmitter
            if event["event"] == "stage":
                emitter.emit_stage(event["name"])
            elif event["event"] == "progress":
                emitter.emit_progress(event["current"], event["total"], event.get("stage"))
            elif event["event"] == "file_done":
                emitter.emit_file_done(event["file"], event["result"])
            elif event["event"] == "error":
                emitter.emit_error(event["code"], event["message"], event.get("file"))
            elif event["event"] == "summary":
                emitter.emit_summary(event["report"])
            elif event["event"] == "cancelled":
                emitter.emit_error("CANCELLED", "Operation cancelled by user")
                emitter._write({"event": "cancelled"})

    else:
        def callback(event: dict[str, Any]) -> None:
            # Simplified human-readable print
            if event["event"] == "stage":
                print(f"\n--- {event['name']} ---")
            elif event["event"] == "progress":
                # Print progress to stdout (tqdm would normally handle this)
                pass
            elif event["event"] == "error":
                print(f"Error [{event['code']}]: {event['message']}")

    modes = ["photo", "video", "audio"] if args.mode == "all" else [args.mode]
    results = []
    
    # Create service
    service = MediaPipelineService(
        mode=modes[0], # Handling all modes iteratively
        target_folder=target_folder,
        config_path=args.config_path,
        progress_callback=callback,
    )
    
    # Setup signal handler
    signal.signal(signal.SIGINT, lambda s, f: service.cancel())
    
    service.set_dry_run(args.dry_run)
    
    # This loop needs to be adapted for "all" mode
    # For now, simplistic approach
    for mode in modes:
        service.mode = mode
        result = service.run()
        results.append(result.get("status") == "success")

    if args.json:
        emitter.close()

    return 0 if all(results) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _build_base_parser()
    args = parser.parse_args(argv)
    
    if not hasattr(args, "mode"):
        parser.print_help()
        return 0
    
    return _run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
