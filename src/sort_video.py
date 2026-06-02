"""Video-only sorting pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qc_video import analyze_video
from pipeline import PipelineConfig, run_media_pipeline


def sort_video(
    target_folder: Path,
    config_path: Path | None = None,
    verbose: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> int:
    """Sort videos only."""
    config = PipelineConfig(
        media_type="video",
        qc_function=analyze_video,
        enable_burst=False,
    )
    return run_media_pipeline(target_folder, config_path, verbose, config, progress_callback=progress_callback)
