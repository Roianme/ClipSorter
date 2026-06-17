from __future__ import annotations

import os
os.environ["CLIPSORTER_GUI_MODE"] = "1"

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Any, Optional, Callable
import urllib.request
import json
import time
import logging
from packaging import version

try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass

from src.service import MediaPipelineService
from src.gui_utils import ToolTip, SettingsManager, GUILogHandler
from src.welcome_view import WelcomeView
from src.live_viewer import LiveViewFrame
from src.version import __version__
from src.binary_resolver import check_all_dependencies, resolve_binary, FFMPEG_ENV_KEY, FFPROBE_ENV_KEY


# Try loading optional dependencies
HAS_DND = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except ImportError:
    BaseTk = tk.Tk

MODE_OPTIONS = [
    ("All media", "all"),
    ("Photos only", "photo"),
    ("Videos only", "video"),
    ("Audio only", "audio"),
]

SETTINGS_FILE = Path.home() / ".clipsorter" / "gui_settings.json"
GITHUB_REPO = "Roianme/ClipSorter" # Correct repo for update checking

class ClipSorterApp:
    def __init__(self) -> None:
        global HAS_DND
        try:
            self.root = BaseTk()
        except Exception:
            # Fallback if BaseTk (TkinterDnD) fails at runtime due to env issues
            self.root = tk.Tk()
            HAS_DND = False
            
        self.root.title(f"ClipSorter v{__version__} [BETA]")
        
        self.settings = SettingsManager(SETTINGS_FILE)
        self.gui_state = self.settings.load()
        
        geometry = self.gui_state.get("geometry", "500x400")
        self.root.geometry(geometry)
        self.root.minsize(500, 400)

        # Check for FFmpeg/FFprobe binaries on startup
        missing_binaries = check_all_dependencies()
        if missing_binaries:
            self._show_missing_ffmpeg_dialog(missing_binaries)
            self.root.destroy() # Exit app if essential binaries are missing
            return
            
        self.folder_path: Optional[Path] = None
        self.mode_var = tk.StringVar(value=self.gui_state.get("mode", "all"))
        
        self.status_var = tk.StringVar(value="Select a folder to begin.")
        self.progress_var = tk.DoubleVar(value=0)
        
        self.service: Optional[MediaPipelineService] = None
        self.worker_thread: Optional[threading.Thread] = None

        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        self._create_widgets()
        self._create_menu()
        
        # Setup GUI logging
        self.gui_handler = GUILogHandler(self._log, self.root)
        self.gui_handler.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))
        logging.getLogger().addHandler(self.gui_handler)
        
        # Bind keyboard shortcuts
        self.root.bind("<Control-Return>", lambda e: self._start_pipeline(dry_run=False))
        self.root.bind("<Shift-Return>", lambda e: self._start_pipeline(dry_run=True))
        self.root.bind("<Escape>", lambda e: self._cancel_pipeline())

        # First launch welcome and auto-update check
        if self.gui_state.get("first_launch", True):
            self.show_welcome()
        
        self._schedule_update_check()

    def _create_menu(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Getting Started", command=self.show_welcome)
        help_menu.add_command(label="Check for Updates", command=lambda: self.check_for_updates(manual=True))
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    def show_welcome(self) -> None:
        # Clear main container and show welcome view
        for child in self.main_container.winfo_children():
            child.pack_forget()
        
        WelcomeView(self.main_container, self._close_welcome).pack(fill="both", expand=True)

    def _close_welcome(self, dont_show: bool) -> None:
        self.gui_state["first_launch"] = not dont_show
        self.settings.save(self.gui_state)
        # Restore main widgets
        for child in self.main_container.winfo_children():
            child.pack_forget()
        self._create_widgets()

    def _schedule_update_check(self) -> None:
        last_check = self.gui_state.get("last_update_check", 0)
        if time.time() - last_check > 86400: # 24 hours
            threading.Thread(target=self.check_for_updates, args=(False,), daemon=True).start()

    def check_for_updates(self, manual: bool = False) -> None:
        if manual:
            self.status_var.set("Checking for updates...")
        
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode())
                latest_version = data["tag_name"].lstrip('v')
                
                if version.parse(latest_version) > version.parse(__version__):
                    messagebox.showinfo("Update Available", f"A new version of ClipSorter is available: {latest_version} (you have {__version__}).")
                elif manual:
                    messagebox.showinfo("Update Check", "You are up-to-date!")
                    
            self.gui_state["last_update_check"] = time.time()
            self.settings.save(self.gui_state)
            
        except Exception as e:
            if manual:
                messagebox.showerror("Update Error", f"Could not check for updates: {e}")
        finally:
            if manual:
                self.status_var.set("Ready")

    def _show_missing_ffmpeg_dialog(self, missing: list[str]) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Missing FFmpeg/FFprobe")
        dialog.transient(self.root)
        dialog.grab_set()

        message = (
            f"""ClipSorter needs FFmpeg to process videos and audio.
The following essential tools were not found: {', '.join(missing)}.

Please install FFmpeg or point to its location."""
        )
        ttk.Label(dialog, text=message, wraplength=400, justify="left").pack(padx=20, pady=20)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)

        # Download button
        ttk.Button(btn_frame, text="Download FFmpeg", command=lambda: self._open_url("https://ffmpeg.org/download.html")).pack(side="left", padx=5)

        # Browse button
        ttk.Button(btn_frame, text="Browse for Folder...", command=lambda: self._browse_for_ffmpeg(dialog, missing)).pack(side="left", padx=5)

        self.root.wait_window(dialog) # Wait for dialog to close

    def _open_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open_new(url)

    def _browse_for_ffmpeg(self, dialog: tk.Toplevel, missing_binaries: list[str]) -> None:
        folder = filedialog.askdirectory(title="Locate FFmpeg/FFprobe Folder")
        if folder:
            path_to_check = Path(folder)
            
            found_all = True
            for binary_name in missing_binaries:
                binary_path = path_to_check / (binary_name + (".exe" if os.name == "nt" else ""))
                if not binary_path.exists():
                    found_all = False
                    break
            
            if found_all:
                # Store paths in environment variables for binary_resolver
                os.environ[FFMPEG_ENV_KEY] = str(path_to_check / ("ffmpeg" + (".exe" if os.name == "nt" else "")))
                os.environ[FFPROBE_ENV_KEY] = str(path_to_check / ("ffprobe" + (".exe" if os.name == "nt" else "")))
                messagebox.showinfo("FFmpeg Found", "FFmpeg and FFprobe found and configured. Please restart ClipSorter.")
                dialog.destroy()
            else:
                messagebox.showwarning("Not Found", f"Could not find all required binaries ({', '.join(missing_binaries)}) in the selected folder. Please try again.")


    def _create_widgets(self) -> None:
        frame = ttk.Frame(self.main_container, padding=16)
        frame.pack(fill="both", expand=True)

        # Folder Selection
        ttk.Label(frame, text="Target Folder:").pack(anchor="w")
        folder_row = ttk.Frame(frame)
        folder_row.pack(fill="x", pady=(0, 10))
        self.folder_entry = ttk.Entry(folder_row)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.folder_entry.bind("<KeyRelease>", self._validate_folder)
        
        browse_btn = ttk.Button(folder_row, text="Browse", command=self._choose_folder)
        browse_btn.pack(side="left", padx=5)
        ToolTip(browse_btn, "Browse for a target folder containing media files.")
        
        if HAS_DND:
            self.folder_entry.drop_target_register(DND_FILES)
            self.folder_entry.dnd_bind('<<Drop>>', self._on_dnd_drop)
        
        ToolTip(self.folder_entry, """The folder containing your media files to organize.
Drag and drop a folder here.""")

        # Mode & Options
        ttk.Label(frame, text="Mode:").pack(anchor="w")
        mode_frame = ttk.Frame(frame)
        mode_frame.pack(fill="x", pady=(0, 10))
        for text, mode in MODE_OPTIONS:
            rb = ttk.Radiobutton(mode_frame, text=text, variable=self.mode_var, value=mode)
            rb.pack(side="left", padx=5)
        ToolTip(mode_frame, "Choose the type of media to process (photo, video, audio).")

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=10)
        self.run_button = ttk.Button(btn_frame, text="Run (Ctrl+Enter)", command=lambda: self._start_pipeline(False), state="disabled")
        self.run_button.pack(side="left", padx=5)
        ToolTip(self.run_button, "Start organizing (Ctrl+Enter)")
        
        self.preview_button = ttk.Button(btn_frame, text="Preview (Shift+Enter)", command=lambda: self._start_pipeline(True), state="disabled")
        self.preview_button.pack(side="left", padx=5)
        ToolTip(self.preview_button, "Preview changes without moving or converting any files (Shift+Enter)")

        self.cancel_button = ttk.Button(btn_frame, text="Cancel (Escape)", command=self._cancel_pipeline, state="disabled")
        self.cancel_button.pack(side="left", padx=5)
        ToolTip(self.cancel_button, "Stop the current operation (Escape)")
        
        self.open_button = ttk.Button(btn_frame, text="Open Output Folder", command=self._open_output, state="disabled")
        self.open_button.pack(side="left", padx=5)
        
        # Manual Viewer Button
        self.manual_button = ttk.Button(btn_frame, text="Manual", command=self._launch_live_view, state="disabled")
        self.manual_button.pack(side="left", padx=5)
        ToolTip(self.manual_button, "Open live photo viewer for manual sorting.")

        # Progress
        self.status_label = ttk.Label(frame, textvariable=self.status_var, justify="center")
        self.status_label.pack(anchor="center", pady=(10, 0))
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=1)
        self.progress_bar.pack(fill="x", pady=5)

        # Logs
        self.log_text = tk.Text(frame, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True, pady=10)

    def _launch_live_view(self) -> None:
        if self.folder_path and self.folder_path.exists():
            LiveViewFrame(self.root, self.folder_path)

    def _validate_folder(self, event: Any = None) -> None:
        path_str = self.folder_entry.get()
        path = Path(path_str)
        is_valid = path.exists() and path.is_dir()
        
        if is_valid:
            self.folder_path = path
            self.folder_entry.config(foreground="")
            if not self.worker_thread or not self.worker_thread.is_alive():
                self.run_button.config(state="normal")
                self.preview_button.config(state="normal")
                self.manual_button.config(state="normal")
        else:
            self.folder_entry.config(foreground="red")
            self.run_button.config(state="disabled")
            self.preview_button.config(state="disabled")
            self.manual_button.config(state="disabled")

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.folder_entry.delete(0, tk.END)
            self.folder_entry.insert(0, folder)
            self._validate_folder()

    def _on_dnd_drop(self, event: Any) -> None:
        # Handle Windows path format
        path = event.data.strip('{}')
        self.folder_entry.delete(0, tk.END)
        self.folder_entry.insert(0, path)
        self._validate_folder()

    def _open_output(self) -> None:
        if self.service and self.service.final_summary:
            output_folder = Path(self.service.final_summary.get("output_folder", ""))
            if output_folder.exists():
                os.startfile(output_folder)
            else:
                messagebox.showerror("Error", f"Output folder not found: {output_folder}")

    def _start_pipeline(self, dry_run: bool) -> None:
        if not self.folder_path or not self.folder_path.exists():
            return

        self.run_button.config(state="disabled")
        self.preview_button.config(state="disabled")
        self.manual_button.config(state="disabled")
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
        self.service.set_dry_run(dry_run)
        
        self.worker_thread = threading.Thread(target=self.service.run)
        self.worker_thread.start()

    def _handle_event(self, event: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._update_ui(event))

    def _update_ui(self, event: dict[str, Any]) -> None:
        event_type = event.get("event")
        
        if event_type == "stage":
            self.status_var.set(event["name"])
            self.progress_var.set(0) # Reset progress for new stage
        elif event_type == "progress":
            self.progress_bar.config(maximum=event["total"])
            self.progress_var.set(event["current"])
        elif event_type == "sub_progress":
            # Real-time sub-progress for a single file (0.0 to 1.0)
            percent = event.get("percent", 0.0)
            self.progress_bar.config(maximum=1.0)
            self.progress_var.set(percent)
            
            # Update status with percentage
            current_stage = self.status_var.get().split("(")[0].strip()
            filename = event.get("filename", "")
            self.status_var.set(f"{current_stage} ({percent*100:.1f}%) : {filename}")
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
        self.preview_button.config(state="normal")
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
        # Save settings
        self.gui_state.update({
            "geometry": self.root.winfo_geometry(),
            "mode": self.mode_var.get()
        })
        self.settings.save(self.gui_state)
        
        if self.worker_thread and self.worker_thread.is_alive():
            if self.service:
                self.service.cancel()
            self.worker_thread.join(timeout=2)
        self.root.destroy()

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    ClipSorterApp().run()
