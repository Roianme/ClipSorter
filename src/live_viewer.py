import io
import tkinter as tk
from PIL import Image, ImageTk
from pathlib import Path

class LiveViewFrame(tk.Toplevel):
    """A non-blocking photo viewer that displays images from a folder."""
    def __init__(self, parent: tk.Widget, folder_path: Path):
        super().__init__(parent)
        self.folder_path = folder_path
        self.title(f"Live View - {folder_path.name}")
        self.attributes('-fullscreen', True)
        
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
        self.display_image(self.image_paths[self.current_index])
        
        self.bind("<Escape>", lambda e: self.destroy())

    def _load_image(self, path: Path) -> Image.Image:
        """Reads image into memory and closes file handle immediately."""
        with open(path, "rb") as f:
            data = f.read()
        return Image.open(io.BytesIO(data))

    def display_image(self, path: Path):
        """Displays the loaded image, scaled to screen."""
        image = self._load_image(path)
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        image.thumbnail((screen_width, screen_height))
        self.tk_image = ImageTk.PhotoImage(image)
        self.label.config(image=self.tk_image)
