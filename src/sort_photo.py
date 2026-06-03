"""Photo-only sorting pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qc_photo import analyze_photo
from pipeline import PipelineConfig, run_media_pipeline
import pipeline_shared as ps


def sort_photo(
    target_folder: Path,
    config_path: Path | None = None,
    verbose: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    json_emitter: Any | None = None,
    dry_run: bool = False,
    cancel_token: Optional[ps.CancellationToken] = None,
) -> int:
    """Sort photos only."""
    config = PipelineConfig(
        media_type="photo",
        qc_function=analyze_photo,
        enable_burst=True,
    )
    return run_media_pipeline(
        target_folder, config_path, verbose, config,
        progress_callback=progress_callback, json_emitter=json_emitter,
        dry_run=dry_run, cancel_token=cancel_token,
    )
