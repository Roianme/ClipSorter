"""CLI module for separate media type sorting."""

from __future__ import annotations

import argparse
import sys
import signal
from pathlib import Path
from typing import Any

from pipeline_shared import JsonEmitter, CancellationToken
from sort_photo import sort_photo
from sort_video import sort_video
from sort_audio import sort_audio


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
        description="Media sorting pipeline with separate photo, video, and audio processing."
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
        # Photo command
    photo_parser = subparsers.add_parser("photo", help="Sort photos only")
    photo_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(photo_parser)
    photo_parser.set_defaults(func=_run_photo)
    
    # Video command
    video_parser = subparsers.add_parser("video", help="Sort videos only")
    video_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(video_parser)
    video_parser.set_defaults(func=_run_video)
    
    # Audio command
    audio_parser = subparsers.add_parser("audio", help="Sort audio files only")
    audio_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(audio_parser)
    audio_parser.set_defaults(func=_run_audio)
    
    # All command
    all_parser = subparsers.add_parser("all", help="Sort all media types (photo, video, audio)")
    all_parser.add_argument("target_folder", help="Path to the source media folder")
    _add_common_args(all_parser)
    all_parser.set_defaults(func=_run_all)
    
    return parser


def _validate_folder(args: Any) -> Path | None:
    """Validate target folder exists and is a directory. Returns Path or prints error."""
    target_folder = Path(args.target_folder)
    if not target_folder.exists() or not target_folder.is_dir():
        if getattr(args, "json", False):
            emitter = JsonEmitter()
            emitter.emit_error(
                "INVALID_FOLDER",
                f"Target folder does not exist or is not a directory: {target_folder}",
            )
            emitter.close()
        else:
            print(f"Error: Target folder does not exist or is not a directory: {target_folder}")
        return None
    return target_folder


def _make_emitter(args: Any) -> JsonEmitter | None:
    """Create a JsonEmitter if --json was passed, otherwise return None."""
    if getattr(args, "json", False):
        return JsonEmitter(sys.stdout)
    return None


def _run_photo(args, cancel_token: CancellationToken) -> int:
    """Run photo sorting."""
    target_folder = _validate_folder(args)
    if target_folder is None:
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    json_emitter = _make_emitter(args)
    return sort_photo(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )


def _run_video(args, cancel_token: CancellationToken) -> int:
    """Run video sorting."""
    target_folder = _validate_folder(args)
    if target_folder is None:
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    json_emitter = _make_emitter(args)
    return sort_video(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )


def _run_audio(args, cancel_token: CancellationToken) -> int:
    """Run audio sorting."""
    target_folder = _validate_folder(args)
    if target_folder is None:
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    json_emitter = _make_emitter(args)
    return sort_audio(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )


def _run_all(args, cancel_token: CancellationToken) -> int:
    """Run all media type sorting."""
    target_folder = _validate_folder(args)
    if target_folder is None:
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    json_emitter = _make_emitter(args)
    
    if json_emitter is None:
        print("=" * 60)
        if args.dry_run:
            print("DRY RUN: Running PHOTO sorting...")
        else:
            print("Running PHOTO sorting...")
        print("=" * 60)
    
    result_photo = sort_photo(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )
    
    if json_emitter is None:
        print("\n" + "=" * 60)
        if args.dry_run:
            print("DRY RUN: Running VIDEO sorting...")
        else:
            print("Running VIDEO sorting...")
        print("=" * 60)
    
    result_video = sort_video(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )
    
    if json_emitter is None:
        print("\n" + "=" * 60)
        if args.dry_run:
            print("DRY RUN: Running AUDIO sorting...")
        else:
            print("Running AUDIO sorting...")
        print("=" * 60)
    
    result_audio = sort_audio(
        target_folder, config_path, args.verbose,
        json_emitter=json_emitter,
        dry_run=args.dry_run,
        cancel_token=cancel_token,
    )
    
    if json_emitter:
        json_emitter.close()
    
    # Return 0 only if all succeeded
    return 0 if all([result_photo == 0, result_video == 0, result_audio == 0]) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _build_base_parser()
    args = parser.parse_args(argv)
    
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    
    token = CancellationToken()
    signal.signal(signal.SIGINT, lambda s, f: token.cancel())
    
    return args.func(args, token)


if __name__ == "__main__":
    raise SystemExit(main())
