from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable
from src.version import __version__


class WelcomeView(ttk.Frame):
    def __init__(self, parent: tk.Widget, on_close: Callable[[bool], None]) -> None:
        super().__init__(parent)
        self.on_close = on_close
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # Title
        ttk.Label(
            self,
            text=f"ClipSorter v{__version__}",
            font=("Arial", 16, "bold"),
            anchor="center",
        ).grid(row=0, column=0, pady=(16, 2), sticky="ew")

        ttk.Label(
            self,
            text="Organize your media files automatically — non-destructively.",
            font=("Arial", 10),
            foreground="gray",
            anchor="center",
        ).grid(row=1, column=0, pady=(0, 12), sticky="ew")

        ttk.Separator(self, orient="horizontal").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(0, 12)
        )

        # Scrollable content area
        container = ttk.Frame(self)
        container.grid(row=3, column=0, sticky="nsew", padx=20)
        container.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        sections = [
            (
                "How it works",
                [
                    "ClipSorter copies your files into a new sibling folder — your originals are never touched.",
                    "Preparation  →  converts media to standard formats (JPEG, MP4, MP3).",
                    "Photos  →  detects duplicates, blurry shots, and burst groups.",
                    "Videos  →  checks duration and steadiness; isolates defective clips.",
                    "Audio  →  validates files for quality and proper formatting.",
                ],
            ),
            (
                "File renaming",
                [
                    "Files are renamed for consistency using this pattern:",
                    "    [SourceFolder]_[Type]_[Number].[Ext]",
                    "    Example:  MyMedia_video_0001.mp4",
                ],
            ),
            (
                "Output folders",
                [
                    "review/  →  media that passed or needs a quick look.",
                    "defects/  →  media that failed quality checks.",
                    "_report.txt  →  full log of every decision made.",
                ],
            ),
            (
                "Quick start",
                [
                    "1.  Choose a source folder.",
                    "2.  Select the media type to process.",
                    "3.  Preview the results.",
                    "4.  Run.",
                ],
            ),
        ]

        for i, (heading, bullets) in enumerate(sections):
            ttk.Label(
                container,
                text=heading,
                font=("Arial", 10, "bold"),
            ).grid(row=i * 2, column=0, sticky="w", pady=(10, 2))

            bullet_text = "\n".join(f"  •  {line}" if not line.startswith(" ") else line for line in bullets)
            ttk.Label(
                container,
                text=bullet_text,
                font=("Arial", 10),
                justify="left",
                wraplength=440,
                anchor="w",
            ).grid(row=i * 2 + 1, column=0, sticky="w", padx=(8, 0))

        ttk.Separator(self, orient="horizontal").grid(
            row=4, column=0, sticky="ew", padx=20, pady=(14, 8)
        )

        # Footer controls
        footer = ttk.Frame(self)
        footer.grid(row=5, column=0, pady=(0, 14), padx=20, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self.dont_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            footer,
            text="Don't show this again",
            variable=self.dont_show_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Button(
            footer,
            text="Get Started →",
            command=self._close,
        ).grid(row=0, column=1, sticky="e")

        self.bind("<Configure>", self._on_resize)
        self._labels: list[ttk.Label] = [
            w for w in container.winfo_children() if isinstance(w, ttk.Label) and w.cget("font") == "Arial 10"
        ]

    def _on_resize(self, event: tk.Event) -> None:
        new_wrap = max(100, event.width - 60)
        for widget in self.winfo_children():
            self._update_wraplength(widget, new_wrap)

    def _update_wraplength(self, widget: tk.Widget, wrap: int) -> None:
        if isinstance(widget, ttk.Label):
            try:
                widget.config(wraplength=wrap)
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._update_wraplength(child, wrap)

    def _close(self) -> None:
        self.on_close(self.dont_show_var.get())