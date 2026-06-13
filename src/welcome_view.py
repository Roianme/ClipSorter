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

        # Title with BETA badge
        header_frame = ttk.Frame(self)
        header_frame.grid(row=0, column=0, pady=(16, 2))
        
        ttk.Label(
            header_frame,
            text=f"ClipSorter v{__version__}",
            font=("Arial", 16, "bold"),
        ).pack(side="left")
        
        beta_label = tk.Label(
            header_frame,
            text="BETA",
            font=("Arial", 9, "bold"),
            bg="#f39c12",
            fg="white",
            padx=4,
            pady=1,
        )
        beta_label.pack(side="left", padx=10)

        ttk.Label(
            self,
            text="Professional Media Quality Control & Smart Organization",
            font=("Arial", 10),
            foreground="gray",
            anchor="center",
        ).grid(row=1, column=0, pady=(0, 12), sticky="ew")

        ttk.Separator(self, orient="horizontal").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(0, 12)
        )

        # Content Container
        container = ttk.Frame(self)
        container.grid(row=3, column=0, sticky="nsew", padx=30)
        container.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        intro_text = (
            "ClipSorter is non-destructive. It reads your raw media and creates an organized "
            "copy in a new folder. Your original files are NEVER deleted."
        )
        ttk.Label(
            container,
            text=intro_text,
            font=("Arial", 10, "italic"),
            foreground="#2980b9",
            justify="center",
            wraplength=480,
        ).grid(row=0, column=0, pady=(0, 15))

        # Button Guide Section
        guide_frame = ttk.LabelFrame(container, text=" How to use the controls ", padding=10)
        guide_frame.grid(row=1, column=0, sticky="ew")
        guide_frame.columnconfigure(1, weight=1)

        buttons = [
            ("Browse", "Select the folder containing your raw photos, videos, or audio."),
            ("Preview", "See what WOULD happen without actually moving or converting any files."),
            ("Run", "Start the full process. Files will be converted, analyzed, and sorted."),
            ("Manual", "Opens a fast viewer for you to manually pick which photos to keep."),
            ("Cancel", "Safely stop the current operation at any time."),
        ]

        for i, (btn_name, desc) in enumerate(buttons):
            tk.Label(
                guide_frame, 
                text=btn_name, 
                font=("Arial", 9, "bold"), 
                fg="#2c3e50",
                width=8,
                anchor="e"
            ).grid(row=i, column=0, padx=(0, 10), pady=3, sticky="ne")
            
            ttk.Label(
                guide_frame, 
                text=desc, 
                font=("Arial", 9),
                wraplength=380,
                justify="left"
            ).grid(row=i, column=1, pady=3, sticky="nw")

        # Results Guide
        results_frame = ttk.Frame(container, padding=(0, 15))
        results_frame.grid(row=2, column=0, sticky="ew")
        results_frame.columnconfigure(0, weight=1)

        ttk.Label(
            results_frame,
            text="Understanding your results:",
            font=("Arial", 10, "bold")
        ).grid(row=0, column=0, sticky="w")

        results_text = (
            "• review/  →  Clean files and those that need a quick human check.\n"
            "• defects/ →  Files that are very blurry, shaky, silent, or dark.\n"
            "• _report.txt → A full list of every quality check and decision made."
        )
        ttk.Label(
            results_frame,
            text=results_text,
            font=("Arial", 9),
            justify="left"
        ).grid(row=1, column=0, sticky="w", padx=15, pady=5)

        ttk.Separator(self, orient="horizontal").grid(
            row=4, column=0, sticky="ew", padx=20, pady=(10, 8)
        )

        # Footer controls
        footer = ttk.Frame(self)
        footer.grid(row=5, column=0, pady=(0, 14), padx=20, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self.dont_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            footer,
            text="Don't show this guide again",
            variable=self.dont_show_var,
        ).grid(row=0, column=0, sticky="w")

        ttk.Button(
            footer,
            text="Start Using ClipSorter →",
            command=self._close,
        ).grid(row=0, column=1, sticky="e")

        self.bind("<Configure>", self._on_resize)

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
