import io
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import logging
from PIL import Image, ImageTk
from pathlib import Path
from src.mover import manual_move

logger = logging.getLogger(__name__)

class LiveViewFrame(tk.Toplevel):
    """A non-blocking photo viewer with manual move capability via shortcuts."""
    def __init__(self, parent: tk.Widget, folder_path: Path):
        super().__init__(parent)
        self.folder_path = folder_path
        self.title(f"Live View - {folder_path.name}")
        self.attributes('-fullscreen', True)
        
        # Shortcut mapping: {key: Path}
        self.shortcuts: dict[int, Path] = {}
        # Shortcut label mapping: {key: tk.Label}
        self.shortcut_labels: dict[int, tk.Label] = {}
        
        self.image_cache = {} # Key: path, Value: (original_pil, display_pil)
        
        # Scan folder for supported images, filter out unreadable ones
        valid_paths = []
        for p in sorted(folder_path.iterdir()):
            if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}:
                try:
                    with Image.open(p) as img:
                        img.verify()
                    valid_paths.append(p)
                except Exception as e:
                    logger.warning(f"Skipping unreadable image {p.name}: {e}")
        self.image_paths = valid_paths
        
        if not self.image_paths:
            self.destroy()
            return
            
        self.current_index = 0
        
        # Main container
        self.main_container = tk.Frame(self, bg="black")
        self.main_container.pack(expand=True, fill="both")
        
        self.label = tk.Label(self.main_container, bg="black")
        self.label.pack(expand=True, fill="both")
        
        # Overlay for info/buttons
        self.overlay = tk.Frame(self, bg="#333333")
        self.overlay.pack(side="bottom", fill="x")

        # Status and Feedback panel
        self.info_panel = tk.Frame(self.overlay, bg="#333333")
        self.info_panel.pack(side="top", fill="x", pady=5)
        
        self.status_label = tk.Label(self.info_panel, text="", bg="#333333", fg="white", font=("Arial", 12))
        self.status_label.pack(side="left", padx=10)
        
        self.feedback_label = tk.Label(self.info_panel, text="", bg="#333333", fg="#ffff00", font=("Arial", 12))
        self.feedback_label.pack(side="right", padx=10)

        # Shortcut panel
        self.shortcut_frame = tk.Frame(self.overlay, bg="#333333")
        self.shortcut_frame.pack(side="top", fill="x", pady=5)

        # Buttons
        btn_frame = tk.Frame(self.overlay, bg="#333333")
        btn_frame.pack(side="bottom", fill="x", pady=10)
        
        ttk.Button(btn_frame, text="Previous", command=self.previous_image).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="Next", command=self.next_image).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="Set Shortcut", command=self.add_shortcut).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="Exit", command=self.destroy).pack(side="right", padx=10)
        
        # Display the first image
        self.show_image(self.current_index)
        
        # Bindings
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Right>", lambda e: self.next_image())
        self.bind("<Left>", lambda e: self.previous_image())
        for i in range(1, 10):
            self.bind(f"{i}", lambda e, idx=i: self.move_to_shortcut(idx))
            self.bind(f"<Control-{i}>", lambda e, idx=i: self.remove_shortcut(idx))

    def _load_image(self, path: Path) -> Image.Image:
        with open(path, "rb") as f:
            data = f.read()
        return Image.open(io.BytesIO(data))

    def show_image(self, index: int, direction: int = 1):
        if not self.image_paths:
            return
        path = self.image_paths[index]
        try:
            if path not in self.image_cache:
                # Load and cache
                original_image = self._load_image(path)
                display_image = original_image.copy()
                
                screen_width = self.winfo_screenwidth()
                screen_height = self.winfo_screenheight()
                # Subtract overlay height
                display_image.thumbnail((screen_width, screen_height - 150))
                
                self.image_cache[path] = (original_image, display_image)
            
            _, display_image = self.image_cache[path]
            
            self.tk_image = ImageTk.PhotoImage(display_image)
            self.label.config(image=self.tk_image)
            
            # Update status
            self.status_label.config(text=f"Viewing: {path.name} ({self.current_index + 1}/{len(self.image_paths)})")
            self.title(f"Live View - {path.name}")
        
        except Exception as e:
            logger.warning(f"Error loading image {path.name}: {e}. Skipping.")
            # Skip to next image in direction
            self.current_index = (self.current_index + direction) % len(self.image_paths)
            self.show_image(self.current_index, direction)

    def next_image(self):
        """Show next image, wrapping around."""
        self.current_index = (self.current_index + 1) % len(self.image_paths)
        self.show_image(self.current_index, direction=1)

    def previous_image(self):
        """Show previous image, wrapping around."""
        self.current_index = (self.current_index - 1) % len(self.image_paths)
        self.show_image(self.current_index, direction=-1)

    def add_shortcut(self):
        folder = filedialog.askdirectory(title="Select Shortcut Folder")
        if folder:
            num = len(self.shortcuts) + 1
            if num > 9:
                messagebox.showwarning("Max Shortcuts", "Maximum 9 shortcuts allowed.")
                return
            self.shortcuts[num] = Path(folder)
            
            # Add to shortcut panel
            lbl = tk.Label(self.shortcut_frame, text=f"{num}: {Path(folder).name}", bg="#333333", fg="cyan", padx=10)
            lbl.pack(side="left")
            self.shortcut_labels[num] = lbl
            
            self.show_feedback(f"Shortcut {num} set to {Path(folder).name}")

    def remove_shortcut(self, num: int):
        if num in self.shortcuts:
            del self.shortcuts[num]
            lbl = self.shortcut_labels.pop(num)
            lbl.destroy()
            self.show_feedback(f"Shortcut {num} removed.")
        else:
            self.show_feedback(f"Shortcut {num} not defined.")

    def move_to_shortcut(self, num: int):
        if num not in self.shortcuts:
            self.show_feedback(f"Shortcut {num} not defined.")
            return
            
        path = self.image_paths[self.current_index]
        dest = self.shortcuts[num]
        
        try:
            manual_move(path, dest)
            self.show_feedback(f"Moved: {path.name} -> {dest.name}")
            # Remove from local list and cache
            del self.image_paths[self.current_index]
            del self.image_cache[path]
            
            if not self.image_paths:
                self.destroy()
            else:
                self.current_index = self.current_index % len(self.image_paths)
                self.show_image(self.current_index)
        except Exception as e:
            self.show_feedback(f"Error moving file: {e}")

    def show_feedback(self, text: str):
        self.feedback_label.config(text=text)
        self.after(3000, lambda: self.feedback_label.config(text=""))
