import io
import tkinter as tk
from PIL import Image, ImageTk
from pathlib import Path

class LiveViewFrame(tk.Toplevel):
    """A non-blocking photo viewer that displays images from a folder with navigation and caching."""
    def __init__(self, parent: tk.Widget, folder_path: Path):
        super().__init__(parent)
        self.folder_path = folder_path
        self.title(f"Live View - {folder_path.name}")
        self.attributes('-fullscreen', True)
        
        self.image_cache = {} # Key: path, Value: (original_pil, display_pil)
        
        # Scan folder for supported images
        self.image_paths = sorted([
            p for p in folder_path.iterdir() 
            if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
        ])
        
        if not self.image_paths:
            self.destroy()
            return
            
        self.current_index = 0
        self.label = tk.Label(self)
        self.label.pack(expand=True, fill="both")
        
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

    def show_image(self, index: int):
        """Displays image at the given index, using cache if available."""
        path = self.image_paths[index]
        
        if path not in self.image_cache:
            # Load and cache
            original_image = self._load_image(path)
            display_image = original_image.copy()
            
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            display_image.thumbnail((screen_width, screen_height))
            
            self.image_cache[path] = (original_image, display_image)
        
        _, display_image = self.image_cache[path]
        
        self.tk_image = ImageTk.PhotoImage(display_image)
        self.label.config(image=self.tk_image)
        self.title(f"Live View - {path.name} ({index + 1}/{len(self.image_paths)})")

    def next_image(self):
        """Show next image, wrapping around."""
        self.current_index = (self.current_index + 1) % len(self.image_paths)
        self.show_image(self.current_index)

    def previous_image(self):
        """Show previous image, wrapping around."""
        self.current_index = (self.current_index - 1) % len(self.image_paths)
        self.show_image(self.current_index)
