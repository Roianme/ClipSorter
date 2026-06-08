import os
import time
from pathlib import Path
from src.live_viewer import LiveViewFrame
import tkinter as tk

def test_file_locking():
    # Setup
    test_file = Path("test_image.jpg")
    if not test_file.exists():
        # Create a dummy image
        from PIL import Image
        Image.new('RGB', (100, 100), color='red').save(test_file)
    
    root = tk.Tk()
    
    # 1. Open with our non-blocking viewer
    viewer = LiveViewFrame(root, test_file)
    root.update()
    
    # 2. Try to rename the file (which requires a write lock/exclusive access)
    try:
        new_name = Path("test_image_renamed.jpg")
        test_file.rename(new_name)
        print("SUCCESS: File was not locked!")
        new_name.rename(test_file) # Restore
    except OSError as e:
        print(f"FAILURE: File is locked! {e}")
    
    viewer.destroy()
    root.destroy()

if __name__ == "__main__":
    test_file_locking()
