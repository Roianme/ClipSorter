"""GUI utility classes for tooltips, settings management, and logging."""

import json
import logging
import tkinter as tk
from pathlib import Path
from typing import Any, Optional, Callable


class ToolTip:
    """A tooltip widget for Tkinter."""
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tooltip_window: Optional[tk.Toplevel] = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, event: Any = None) -> None:
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(self.tooltip_window, text=self.text, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()

    def hide(self, event: Any = None) -> None:
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class SettingsManager:
    """Manages saving and loading UI settings."""
    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            with open(self.settings_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def save(self, settings: dict[str, Any]) -> None:
        try:
            with open(self.settings_path, "w") as f:
                json.dump(settings, f)
        except IOError:
            pass


class GUILogHandler(logging.Handler):
    """A logging handler that redirects logs to a GUI callback."""
    def __init__(self, log_func: Callable[[str], None], root: tk.Tk) -> None:
        super().__init__()
        self.log_func = log_func
        self.root = root

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.root.after(0, lambda: self.log_func(msg))
