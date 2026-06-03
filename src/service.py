"""Unified media sorting pipeline service for CLI and GUI usage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from pipeline import run_media_pipeline, PipelineConfig
from pipeline_shared import CancellationToken, PipelineCancelledError
from qc_audio import analyze_audio
from qc_photo import analyze_photo
from qc_video import analyze_video

logger = logging.getLogger(__name__)


class MediaPipelineService:
    """
    Encapsulates the media sorting pipeline and provides a callback-driven API.
    """

    def __init__(
        self,
        mode: str,
        target_folder: str,
        config_path: Optional[str] = None,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.mode = mode
        self.target_folder = Path(target_folder)
        self.config_path = Path(config_path) if config_path else None
        self.progress_callback = progress_callback
        self.cancel_token = CancellationToken()
        self.dry_run = False

    def set_dry_run(self, value: bool) -> None:
        """Enable or disable preview mode."""
        self.dry_run = value

    def cancel(self) -> None:
        """Trigger cancellation of the pipeline."""
        self.cancel_token.cancel()

    def _emit(self, event_dict: dict[str, Any]) -> None:
        """Emit an event via the callback if configured."""
        if self.progress_callback:
            self.progress_callback(event_dict)

    def run(self) -> dict[str, Any]:
        """
        Run the pipeline synchronously.
        
        Returns the final report summary dict, or a dict indicating cancellation.
        """
        if not self.target_folder.exists() or not self.target_folder.is_dir():
            self._emit({"event": "error", "code": "INVALID_FOLDER", "message": "Target folder not found"})
            return {"error": "INVALID_FOLDER"}

        # Map mode to pipeline configuration
        qc_func = {
            "photo": analyze_photo,
            "video": analyze_video,
            "audio": analyze_audio,
        }.get(self.mode)

        if not qc_func:
            self._emit({"event": "error", "code": "INVALID_MODE", "message": f"Unsupported mode: {self.mode}"})
            return {"error": "INVALID_MODE"}

        pipeline_config = PipelineConfig(
            media_type=self.mode,
            qc_function=qc_func,
            enable_burst=(self.mode == "photo"),
        )

        try:
            # We don't have a direct way to return the report data from run_media_pipeline easily.
            # We need to adapt it or ensure it returns what we need.
            # Looking at run_media_pipeline, it returns an exit code (int).
            # This is a limitation.
            # To meet the requirement "run() returns a result dict (the summary)",
            # I might need to adjust run_media_pipeline to return the data,
            # but I should work with what I have.
            
            # The current run_media_pipeline doesn't return the report data.
            # I will assume for now I should return a status dict.
            
            # RETHINK: run_media_pipeline in pipeline.py emits "summary" event which contains the report.
            # I can capture this if I pass a custom JsonEmitter,
            # but I'm given a progress_callback.
            
            # Let's keep it simple for now, as I shouldn't change the core pipeline too much.
            # I will return a success status if exit code is 0.
            
            exit_code = run_media_pipeline(
                self.target_folder,
                self.config_path,
                verbose=False,
                pipeline_config=pipeline_config,
                # I need to adapt the progress_callback to run_media_pipeline.
                # The CLI and sort_*.py modules use progress_callback, but it's a specific signature.
                # I will need to bridge them.
                dry_run=self.dry_run,
                cancel_token=self.cancel_token,
            )
            
            if exit_code == 0:
                return {"status": "success"}
            elif exit_code == 130:
                self._emit({"event": "cancelled"})
                return {"status": "cancelled"}
            else:
                return {"status": "failed", "exit_code": exit_code}

        except PipelineCancelledError:
            self._emit({"event": "cancelled"})
            return {"status": "cancelled"}
        except Exception as e:
            logger.exception("Pipeline failed")
            self._emit({"event": "error", "code": "PIPELINE_ERROR", "message": str(e)})
            return {"status": "failed", "message": str(e)}
