import os
import time
from pathlib import Path
import tkinter as tk
import pytest

# Skip if no display
def is_gui_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except (tk.TclError, Exception):
        return False

@pytest.mark.skipif(not is_gui_available(), reason="No display available for GUI tests")
def test_file_locking(tmp_path):
    from src.live_viewer import LiveViewFrame
    # Setup in tmp_path
    test_file = tmp_path / "test_image.jpg"
    
    # Create a dummy image
    from PIL import Image
    Image.new('RGB', (100, 100), color='red').save(test_file)
    
    root = tk.Tk()
    
    # 1. Open with our non-blocking viewer
    viewer = LiveViewFrame(root, test_file)
    root.update()
    
    # 2. Try to rename the file (which requires a write lock/exclusive access)
    try:
        new_name = tmp_path / "test_image_renamed.jpg"
        test_file.rename(new_name)
        # SUCCESS: File was not locked!
        new_name.rename(test_file) # Restore
    except OSError as e:
        pytest.fail(f"File is locked! {e}")
    finally:
        viewer.destroy()
        root.destroy()
