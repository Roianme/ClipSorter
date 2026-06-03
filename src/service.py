"""Unified media sorting pipeline service for CLI and GUI usage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from src.pipeline import run_media_pipeline, PipelineConfig
from src.pipeline_shared import CancellationToken, PipelineCancelledError
from src.qc_audio import analyze_audio
from src.qc_photo import analyze_photo
from src.qc_video import analyze_video

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
        self.final_summary: Optional[dict[str, Any]] = None

    def set_dry_run(self, value: bool) -> None:
        """Enable or disable preview mode."""
        self.dry_run = value

    def cancel(self) -> None:
        """Trigger cancellation of the pipeline."""
        self.cancel_token.cancel()

    def _emit(self, event_dict: dict[str, Any]) -> None:
        """Emit an event via the callback if configured."""
        if self.progress_callback:
            # Capture the summary if emitted
            if event_dict.get("event") == "summary":
                self.final_summary = event_dict.get("report")
            self.progress_callback(event_dict)

    def _handle_internal_callback(self, message: str) -> None:
        """Bridge old-style string tokens to event dicts."""
        if message.startswith("__STAGE__:"):
            self._emit({"event": "stage", "name": message.split(":", 1)[1]})
        elif message.startswith("__PROGRESS__:"):
            parts = message.split(":", 1)[1].split("/")
            if len(parts) == 2:
                self._emit({"event": "progress", "current": int(parts[0]), "total": int(parts[1])})
        elif message.startswith("__SUMMARY__:"):
            import json
            report_data = json.loads(message.split(":", 1)[1])
            self._emit({"event": "summary", "report": report_data})
        else:
            # Fallback/unknown
            pass

    def run(self) -> dict[str, Any]:
        """
        Run the pipeline synchronously.
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
            # Check for cancellation before starting
            from src.pipeline_shared import check_cancelled
            check_cancelled(self.cancel_token)
            
            exit_code = run_media_pipeline(
                self.target_folder,
                self.config_path,
                verbose=False,
                pipeline_config=pipeline_config,
                # Pass the bridge callback
                progress_callback=self._handle_internal_callback,
                dry_run=self.dry_run,
                cancel_token=self.cancel_token,
                # Emitter is optional, and I have a progress_callback.
                # If I want summary event in callback, I'd need to emit it in run_media_pipeline 
                # or ensure progress_callback gets it.
            )
            
            # The summary event is only emitted to json_emitter!
            # I must fix run_media_pipeline to emit it to progress_callback.
            
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
