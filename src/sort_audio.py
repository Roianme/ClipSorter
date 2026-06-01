"""Audio-only sorting pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qc_audio import analyze_audio
from pipeline import PipelineConfig, run_media_pipeline


def sort_audio(target_folder: Path, config_path: Path | None = None, verbose: bool = False) -> int:
    """Sort audio files only."""
    config = PipelineConfig(
        media_type="audio",
        qc_function=analyze_audio,
        enable_burst=False,
    )
    return run_media_pipeline(target_folder, config_path, verbose, config)
