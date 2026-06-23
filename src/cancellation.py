"""Cancellation primitives for the media sorting pipeline."""

from __future__ import annotations

import threading
from typing import Optional


class PipelineCancelledError(Exception):
    """Raised when the pipeline is cancelled by the user."""
    pass


class CancellationToken:
    """
    Thread-safe token used to signal cancellation to the pipeline.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Trigger cancellation."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been triggered."""
        return self._event.is_set()


def check_cancelled(token: Optional[CancellationToken]) -> None:
    """Raise PipelineCancelledError if the token is set."""
    if token is not None and token.is_cancelled():
        raise PipelineCancelledError("Operation cancelled by user")
