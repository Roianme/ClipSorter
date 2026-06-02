from __future__ import annotations

import os
import queue
import sys
import threading
from pathlib import Path
from typing import Callable
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.sort_audio import sort_audio
from src.sort_photo import sort_photo
from src.sort_video import sort_video

MODE_OPTIONS = [
    ("All media", "all"),
    ("Photos only", "photo"),
    ("Videos only", "video"),
    ("Audio only", "audio"),
]


class QueueWriter:
    def __init__(self, queue_: "queue.Queue[str]"):
        self._queue = queue_
        self._buffer = ""

    def write(self, text: str) -> None:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._queue.put(line)

    def flush(self) -> None:
        if self._buffer:
            self._queue.put(self._buffer)
            self._buffer = ""


class ClipSorterApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ClipSorter GUI")
        self.root.geometry("600x360")
        self.root.resizable(False, False)

        self.folder_path: Path | None = None
        self.mode_var = tk.StringVar(value="all")
        self.status_var = tk.StringVar(value="Select a folder to begin.")
        self.summary_var = tk.StringVar(value="")
        self.output_path: Path | None = None
        self.report_path: Path | None = None
        self.log_queue: queue.Queue[str] | None = None
        self.worker_thread: threading.Thread | None = None
        self.current_stage_name: str | None = None

        self._create_frames()
        self._show_frame(self.select_frame)

    def _create_frames(self) -> None:
        self.select_frame = ttk.Frame(self.root, padding=16)
        self.progress_frame = ttk.Frame(self.root, padding=16)
        self.result_frame = ttk.Frame(self.root, padding=16)

        self._build_select_screen()
        self._build_progress_screen()
        self._build_result_screen()

    def _build_select_screen(self) -> None:
        title = ttk.Label(self.select_frame, text="ClipSorter Desktop", font=(None, 18, "bold"))
        title.pack(pady=(0, 16))

        folder_row = ttk.Frame(self.select_frame)
        folder_row.pack(fill="x", pady=(0, 12))

        self.folder_entry = ttk.Entry(folder_row, width=56, state="readonly")
        self.folder_entry.pack(side="left", fill="x", expand=True)

        select_button = ttk.Button(folder_row, text="Select Folder", command=self._choose_folder)
        select_button.pack(side="left", padx=(8, 0))

        mode_label = ttk.Label(self.select_frame, text="Sort mode:")
        mode_label.pack(anchor="w", pady=(4, 8))

        for text, mode in MODE_OPTIONS:
            ttk.Radiobutton(
                self.select_frame,
                text=text,
                variable=self.mode_var,
                value=mode,
            ).pack(anchor="w")

        self.start_button = ttk.Button(
            self.select_frame,
            text="Start Sorting",
            command=self._on_start,
            state="disabled",
        )
        self.start_button.pack(pady=(16, 0))

        self.status_label = ttk.Label(self.select_frame, textvariable=self.status_var, foreground="#444")
        self.status_label.pack(pady=(16, 0), anchor="w")

    def _build_progress_screen(self) -> None:
        title = ttk.Label(self.progress_frame, text="Sorting in progress", font=(None, 16, "bold"))
        title.pack(pady=(0, 12))

        self.progress_label = ttk.Label(self.progress_frame, textvariable=self.status_var, wraplength=560)
        self.progress_label.pack(pady=(0, 16), anchor="w")

        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate", length=520)
        self.progress_bar.pack(pady=(0, 20))

        self.log_text = tk.Text(self.progress_frame, width=70, height=10, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _build_result_screen(self) -> None:
        title = ttk.Label(self.result_frame, text="Sorting complete", font=(None, 18, "bold"))
        title.pack(pady=(0, 16))

        summary = ttk.Label(self.result_frame, textvariable=self.summary_var, wraplength=560)
        summary.pack(pady=(0, 24), anchor="w")

        buttons = ttk.Frame(self.result_frame)
        buttons.pack(fill="x", pady=(0, 20))

        self.open_output_button = ttk.Button(buttons, text="Open Output Folder", command=self._open_output_folder)
        self.open_output_button.pack(side="left", expand=True)

        self.open_report_button = ttk.Button(buttons, text="View Report", command=self._open_report)
        self.open_report_button.pack(side="left", expand=True, padx=(12, 0))

        ttk.Button(self.result_frame, text="Sort Another Folder", command=self._reset).pack()

    def _show_frame(self, frame: ttk.Frame) -> None:
        for child in (self.select_frame, self.progress_frame, self.result_frame):
            child.pack_forget()
        frame.pack(fill="both", expand=True)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select source folder")
        if not folder:
            return

        self.folder_path = Path(folder)
        self.folder_entry.config(state="normal")
        self.folder_entry.delete(0, tk.END)
        self.folder_entry.insert(0, str(self.folder_path))
        self.folder_entry.config(state="readonly")
        self.start_button.config(state="normal")
        self.status_var.set("Ready to sort. Choose a mode and click Start.")

    def _on_start(self) -> None:
        if self.folder_path is None or not self.folder_path.is_dir():
            messagebox.showerror("Invalid folder", "Please select a valid folder before starting.")
            return

        self.status_var.set("Starting pipeline...")
        self.current_stage_name = None
        self._show_frame(self.progress_frame)
        self.progress_bar.config(mode="determinate", value=0, maximum=1)
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

        self.log_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._run_sort, daemon=True)
        self.worker_thread.start()
        self.root.after(100, self._poll_log_queue)

    def _run_sort(self) -> None:
        assert self.folder_path is not None
        assert self.log_queue is not None
        previous_stdout = sys.stdout
        previous_stderr = sys.stderr
        writer = QueueWriter(self.log_queue)
        sys.stdout = writer
        sys.stderr = writer

        try:
            results: list[int] = []
            progress_callback: Callable[[str], None] | None = self.log_queue.put
            if self.mode_var.get() == "all":
                for mode in ("photo", "video", "audio"):
                    self.log_queue.put(f"Running {mode} sorting...")
                    code = self._run_mode(mode, progress_callback=progress_callback)
                    results.append(code)
            else:
                results.append(self._run_mode(self.mode_var.get(), progress_callback=progress_callback))

            self.output_path = self._discover_latest_output()
            self.report_path = self._discover_latest_report()
            self.log_queue.put("__DONE__")
            self._show_results(results)
        except Exception as exc:  # pragma: no cover
            writer.flush()
            error_msg = f"ERROR: {exc}"
            self.log_queue.put(error_msg)
            self.log_queue.put("__DONE__")
            self.summary_var.set(f"Sorting failed: {exc}")
            self.output_path = None
            self.report_path = None
        finally:
            sys.stdout = previous_stdout
            sys.stderr = previous_stderr

    def _run_mode(self, mode: str, progress_callback: Callable[[str], None] | None = None) -> int:
        if mode == "photo":
            return sort_photo(self.folder_path, None, False, progress_callback=progress_callback)
        if mode == "video":
            return sort_video(self.folder_path, None, False, progress_callback=progress_callback)
        if mode == "audio":
            return sort_audio(self.folder_path, None, False, progress_callback=progress_callback)
        raise ValueError(f"Unsupported mode: {mode}")

    def _discover_latest_output(self) -> Path | None:
        if self.folder_path is None:
            return None
        parent = self.folder_path.parent
        prefix = f"{self.folder_path.name}_sorted"
        candidates = [p for p in parent.iterdir() if p.is_dir() and p.name.startswith(prefix)]
        if not candidates:
            return None
        return max(candidates, key=lambda entry: entry.stat().st_mtime)

    def _discover_latest_report(self) -> Path | None:
        output_folder = self._discover_latest_output()
        if output_folder is None:
            return None
        report_file = output_folder / "_report.txt"
        return report_file if report_file.exists() else None

    def _parse_report(self, report_path: Path) -> tuple[int, int]:
        review = 0
        defects = 0
        try:
            with report_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip().startswith("Review:"):
                        review = int(line.strip().split()[-1])
                    elif line.strip().startswith("Defects:"):
                        defects = int(line.strip().split()[-1])
        except Exception:
            pass
        return review, defects

    def _show_results(self, result_codes: list[int]) -> None:
        self.progress_bar.stop()
        self.status_var.set("Sorting complete.")
        self.log_text.config(state="disabled")

        if any(code != 0 for code in result_codes):
            self.summary_var.set("One or more sorting phases finished with errors. See the log above and run again.")
        else:
            summary_lines = ["Sort complete."]
            if self.report_path is not None:
                review, defects = self._parse_report(self.report_path)
                summary_lines.append(f"Review: {review} files")
                summary_lines.append(f"Defects: {defects} files")
                summary_lines.append(f"Output folder: {self.report_path.parent}")
            else:
                summary_lines.append("No report file could be located.")
            self.summary_var.set("\n".join(summary_lines))

        self.open_output_button.config(state="normal" if self.output_path and self.output_path.exists() else "disabled")
        self.open_report_button.config(state="normal" if self.report_path and self.report_path.exists() else "disabled")
        self._show_frame(self.result_frame)

    def _poll_log_queue(self) -> None:
        if self.log_queue is None:
            return
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE__":
                    self.progress_bar.stop()
                    self._show_frame(self.result_frame)
                    return
                self._append_log(line)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _append_log(self, line: str) -> None:
        if line.startswith("__STAGE__:"):
            stage_text = line.split(":", 1)[1]
            self.current_stage_name = stage_text
            self.progress_bar.config(value=0, maximum=1)
            self.status_var.set(stage_text)
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, f"{stage_text}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
            return

        if line.startswith("__PROGRESS__:"):
            progress_text = line.split(":", 1)[1]
            try:
                current, total = [int(value) for value in progress_text.split("/")]
            except ValueError:
                return
            self.progress_bar.config(maximum=total, value=current)
            if self.current_stage_name:
                self.status_var.set(f"{self.current_stage_name} ({current}/{total})")
            else:
                self.status_var.set(f"{current}/{total}")
            return

        is_error = line.startswith("ERROR:")
        self.log_text.config(state="normal")
        if is_error:
            self.log_text.insert(tk.END, f"{line}\n", "error")
            self.log_text.tag_config("error", foreground="red")
        else:
            self.log_text.insert(tk.END, f"{line}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

        if is_error:
            self.progress_bar.stop()
            self.status_var.set("Sorting failed — see errors above.")

    def _open_output_folder(self) -> None:
        if self.output_path is None or not self.output_path.exists():
            return
        os.startfile(self.output_path)

    def _open_report(self) -> None:
        if self.report_path is None or not self.report_path.exists():
            return
        os.startfile(self.report_path)

    def _reset(self) -> None:
        self.folder_path = None
        self.output_path = None
        self.report_path = None
        self.folder_entry.config(state="normal")
        self.folder_entry.delete(0, tk.END)
        self.folder_entry.config(state="readonly")
        self.start_button.config(state="disabled")
        self.status_var.set("Select a folder to begin.")
        self.summary_var.set("")
        self._show_frame(self.select_frame)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = ClipSorterApp()
    app.run()


if __name__ == "__main__":
    main()
