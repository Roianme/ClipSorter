from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable
from src.version import __version__

class WelcomeView(ttk.Frame):
    def __init__(self, parent: tk.Widget, on_close: Callable[[bool], None]) -> None:
        super().__init__(parent)
        self.on_close = on_close
        
        # UI Definition
        ttk.Label(self, text=f"ClipSorter v{__version__}", font=("Arial", 16, "bold")).pack(pady=10)
        ttk.Label(self, text="Organize your media files automatically.", font=("Arial", 12)).pack(pady=5)
        
        info = (
            "ClipSorter is completely non-destructive. It creates organized copies of your "
            "media in a new sibling folder.\n\n"
            "How it works:\n"
            "- PREPARATION: Converts media to standard formats (JPEG, MP4, MP3).\n"
            "- PHOTOS: Detects duplicates, blurry shots, and burst groups.\n"
            "- VIDEOS: Checks duration and steadiness, and isolates defective clips.\n"
            "- AUDIO: Validates files for quality and proper formatting.\n\n"
            "Renaming Mechanics:\n"
            "Files are renamed for consistency: [SourceFolderName]_[Type]_[Number].[Ext]\n"
            "Example: MyMedia_video_0001.mp4\n\n"
            "Expected Output:\n"
            "- 'review/': Sorted media that are good or require a quick look.\n"
            "- 'defects/': Media that failed quality checks (isolated for review).\n"
            "- '_report.txt': A full log of every decision made.\n\n"
            "Steps: 1. Choose folder. 2. Select media type. 3. Preview. 4. Run."
        )
        self.info_label = ttk.Label(self, text=info, justify="center", wraplength=450)
        self.info_label.pack(pady=15, padx=10, anchor="center")
        
        self.bind("<Configure>", self._on_resize)
        
        self.dont_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Don't show this again", variable=self.dont_show_var).pack(pady=10)
        
        ttk.Button(self, text="Get Started", command=self._close).pack(pady=10)

    def _on_resize(self, event: tk.Event) -> None:
        """Update wraplength when the window is resized."""
        # Use slightly less than full width to account for padding
        new_wraplength = event.width - 40
        if new_wraplength > 100:
            self.info_label.config(wraplength=new_wraplength)

    def _close(self) -> None:
        self.on_close(self.dont_show_var.get())
