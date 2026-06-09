import io
import tkinter as tk
from tkinter import ttk
import logging
from PIL import Image, ImageTk
from pathlib import Path

logger = logging.getLogger(__name__)

class LiveViewFrame(tk.Toplevel):
    """A non-blocking photo viewer that displays images from a folder with navigation, caching, and error handling."""
    def __init__(self, parent: tk.Widget, folder_path: Path):
        super().__init__(parent)
        self.folder_path = folder_path
        self.title(f"Live View - {folder_path.name}")
        self.attributes('-fullscreen', True)
        
        self.image_cache = {} # Key: path, Value: (original_pil, display_pil)
        
        # Scan folder for supported images, filter out unreadable ones
        valid_paths = []
        for p in sorted(folder_path.iterdir()):
            if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}:
                try:
                    # Test if readable
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
        
        # Navigation/Exit overlay
        overlay = tk.Frame(self, bg="#333333")
        overlay.pack(side="bottom", fill="x")

        ttk.Button(overlay, text="Previous", command=self.previous_image).pack(side="left", padx=10, pady=10)
        ttk.Button(overlay, text="Next", command=self.next_image).pack(side="left", padx=10, pady=10)
        ttk.Button(overlay, text="Exit", command=self.destroy).pack(side="right", padx=10, pady=10)
        
        # Display the first image
        self.show_image(self.current_index)
        
        # Bindings
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Right>", lambda e: self.next_image())
        self.bind("<Left>", lambda e: self.previous_image())

    def _load_image(self, path: Path) -> Image.Image:
        """Reads image into memory and closes file handle immediately."""
        with open(path, "rb") as f:
            data = f.read()
        return Image.open(io.BytesIO(data))

    def show_image(self, index: int, direction: int = 1):
        """Displays image at the given index, using cache if available. Skips on error."""
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
                display_image.thumbnail((screen_width, screen_height - 50))
                
                self.image_cache[path] = (original_image, display_image)
            
            _, display_image = self.image_cache[path]
            
            self.tk_image = ImageTk.PhotoImage(display_image)
            self.label.config(image=self.tk_image)
            self.title(f"Live View - {path.name} ({self.current_index + 1}/{len(self.image_paths)})")
        
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
