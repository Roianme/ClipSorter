"""CLI module for separate media type sorting."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sort_photo import sort_photo
from sort_video import sort_video
from sort_audio import sort_audio


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
    photo_parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a custom config.json file",
    )
    photo_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    photo_parser.set_defaults(func=_run_photo)
    
    # Video command
    video_parser = subparsers.add_parser("video", help="Sort videos only")
    video_parser.add_argument("target_folder", help="Path to the source media folder")
    video_parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a custom config.json file",
    )
    video_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    video_parser.set_defaults(func=_run_video)
    
    # Audio command
    audio_parser = subparsers.add_parser("audio", help="Sort audio files only")
    audio_parser.add_argument("target_folder", help="Path to the source media folder")
    audio_parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a custom config.json file",
    )
    audio_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    audio_parser.set_defaults(func=_run_audio)
    
    # All command
    all_parser = subparsers.add_parser("all", help="Sort all media types (photo, video, audio)")
    all_parser.add_argument("target_folder", help="Path to the source media folder")
    all_parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to a custom config.json file",
    )
    all_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    all_parser.set_defaults(func=_run_all)
    
    return parser


def _run_photo(args) -> int:
    """Run photo sorting."""
    target_folder = Path(args.target_folder)
    if not target_folder.exists() or not target_folder.is_dir():
        print(f"Error: Target folder does not exist or is not a directory: {target_folder}")
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    return sort_photo(target_folder, config_path, args.verbose)


def _run_video(args) -> int:
    """Run video sorting."""
    target_folder = Path(args.target_folder)
    if not target_folder.exists() or not target_folder.is_dir():
        print(f"Error: Target folder does not exist or is not a directory: {target_folder}")
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    return sort_video(target_folder, config_path, args.verbose)


def _run_audio(args) -> int:
    """Run audio sorting."""
    target_folder = Path(args.target_folder)
    if not target_folder.exists() or not target_folder.is_dir():
        print(f"Error: Target folder does not exist or is not a directory: {target_folder}")
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    return sort_audio(target_folder, config_path, args.verbose)


def _run_all(args) -> int:
    """Run all media type sorting."""
    target_folder = Path(args.target_folder)
    if not target_folder.exists() or not target_folder.is_dir():
        print(f"Error: Target folder does not exist or is not a directory: {target_folder}")
        return 1
    
    config_path = Path(args.config_path) if args.config_path else None
    
    print("=" * 60)
    print("Running PHOTO sorting...")
    print("=" * 60)
    result_photo = sort_photo(target_folder, config_path, args.verbose)
    
    print("\n" + "=" * 60)
    print("Running VIDEO sorting...")
    print("=" * 60)
    result_video = sort_video(target_folder, config_path, args.verbose)
    
    print("\n" + "=" * 60)
    print("Running AUDIO sorting...")
    print("=" * 60)
    result_audio = sort_audio(target_folder, config_path, args.verbose)
    
    # Return 0 only if all succeeded
    return 0 if all([result_photo == 0, result_video == 0, result_audio == 0]) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = _build_base_parser()
    args = parser.parse_args(argv)
    
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
