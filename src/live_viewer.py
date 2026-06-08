import io
import tkinter as tk
from PIL import Image, ImageTk
from pathlib import Path

class LiveViewFrame(tk.Toplevel):
    """A non-blocking photo viewer."""
    def __init__(self, parent: tk.Widget, image_path: Path):
        super().__init__(parent)
        self.image_path = image_path
        self.title(f"Live View - {image_path.name}")
        self.attributes('-fullscreen', True)
        
        self.image_data = self._load_image_non_blocking(image_path)
        
        self.label = tk.Label(self)
        self.label.pack(expand=True, fill="both")
        self.display_image(self.image_data)
        
        self.bind("<Escape>", lambda e: self.destroy())

    def _load_image_non_blocking(self, path: Path) -> Image.Image:
        """Reads image into memory and closes file handle immediately."""
        with open(path, "rb") as f:
            data = f.read()
            # File handle is closed here
        
        # Load image from bytes in memory
        return Image.open(io.BytesIO(data))

    def display_image(self, image: Image.Image):
        """Displays the loaded image."""
        # For simplicity, resize to fit screen (can be optimized later)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        image.thumbnail((screen_width, screen_height))
        self.tk_image = ImageTk.PhotoImage(image)
        self.label.config(image=self.tk_image)
