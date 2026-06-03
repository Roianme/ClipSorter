from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Any, Optional

from src.service import MediaPipelineService
from src.sort_photo import sort_photo
from src.sort_video import sort_video
from src.sort_audio import sort_audio

MODE_OPTIONS = [
    ("All media", "all"),
    ("Photos only", "photo"),
    ("Videos only", "video"),
    ("Audio only", "audio"),
]

class ClipSorterApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ClipSorter GUI")
        self.root.geometry("600x450")

        self.folder_path: Optional[Path] = None
        self.mode_var = tk.StringVar(value="all")
        self.dry_run_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Select a folder to begin.")
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_max = tk.DoubleVar(value=1)
        
        self.service: Optional[MediaPipelineService] = None
        self.worker_thread: Optional[threading.Thread] = None

        self._create_widgets()

    def _create_widgets(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        # Folder Selection
        ttk.Label(frame, text="Target Folder:").pack(anchor="w")
        folder_row = ttk.Frame(frame)
        folder_row.pack(fill="x", pady=(0, 10))
        self.folder_entry = ttk.Entry(folder_row, state="readonly")
        self.folder_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse", command=self._choose_folder).pack(side="left", padx=5)

        # Mode & Options
        ttk.Label(frame, text="Mode:").pack(anchor="w")
        mode_frame = ttk.Frame(frame)
        mode_frame.pack(fill="x", pady=(0, 10))
        for text, mode in MODE_OPTIONS:
            ttk.Radiobutton(mode_frame, text=text, variable=self.mode_var, value=mode).pack(side="left", padx=5)

        ttk.Checkbutton(frame, text="Preview only (no changes)", variable=self.dry_run_var).pack(anchor="w", pady=(0, 10))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=10)
        self.run_button = ttk.Button(btn_frame, text="Run/Preview", command=self._start_pipeline)
        self.run_button.pack(side="left", padx=5)
        self.cancel_button = ttk.Button(btn_frame, text="Cancel", command=self._cancel_pipeline, state="disabled")
        self.cancel_button.pack(side="left", padx=5)
        self.open_button = ttk.Button(btn_frame, text="Open Output Folder", command=self._open_output, state="disabled")
        self.open_button.pack(side="left", padx=5)

        # Progress
        self.status_label = ttk.Label(frame, textvariable=self.status_var)
        self.status_label.pack(anchor="w", pady=(10, 0))
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=1)
        self.progress_bar.pack(fill="x", pady=5)

        # Logs
        self.log_text = tk.Text(frame, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True, pady=10)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path = Path(folder)
            self.folder_entry.config(state="normal")
            self.folder_entry.delete(0, tk.END)
            self.folder_entry.insert(0, str(self.folder_path))
            self.folder_entry.config(state="readonly")

    def _open_output(self) -> None:
        if self.service and self.service.final_summary:
            output_folder = Path(self.service.final_summary.get("output_folder", ""))
            if output_folder.exists():
                import os
                os.startfile(output_folder)
            else:
                messagebox.showerror("Error", f"Output folder not found: {output_folder}")

    def _start_pipeline(self) -> None:
        if not self.folder_path:
            messagebox.showerror("Error", "Please select a target folder.")
            return

        self.run_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.open_button.config(state="disabled")
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        self.status_var.set("Starting...")
        
        mode = self.mode_var.get()
        self.service = MediaPipelineService(
            mode=mode,
            target_folder=str(self.folder_path),
            progress_callback=self._handle_event
        )
        self.service.set_dry_run(self.dry_run_var.get())
        
        self.worker_thread = threading.Thread(target=self.service.run)
        self.worker_thread.start()

    def _handle_event(self, event: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._update_ui(event))

    def _update_ui(self, event: dict[str, Any]) -> None:
        event_type = event.get("event")
        
        if event_type == "stage":
            self.status_var.set(event["name"])
        elif event_type == "progress":
            self.progress_bar.config(maximum=event["total"])
            self.progress_var.set(event["current"])
        elif event_type == "file_done":
            pass
        elif event_type == "error":
            self._log(f"Error [{event.get('code')}]: {event['message']}")
        elif event_type == "summary":
            report = event.get("report", {})
            self._log("Pipeline finished successfully.")
            self._log(f"Review: {report.get('results', {}).get('review')} files")
            self._log(f"Defects: {report.get('results', {}).get('defects')} files")
            self._finalize()
        elif event_type == "cancelled":
            self.status_var.set("Cancelled")
            self._log("Operation cancelled by user.")
            self._finalize()

    def _log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _finalize(self) -> None:
        self.run_button.config(state="normal")
        self.cancel_button.config(state="disabled")
        self.open_button.config(state="normal")

    def _cancel_pipeline(self) -> None:
        if self.service:
            self.status_var.set("Cancelling...")
            self.service.cancel()

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            if self.service:
                self.service.cancel()
            self.worker_thread.join(timeout=2)
        self.root.destroy()

if __name__ == "__main__":
    ClipSorterApp().run()
