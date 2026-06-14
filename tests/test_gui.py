"""
GUI Test Suite for ClipSorter.
Requires a display environment to run (e.g., local developer machine).
"""
import pytest
import tkinter as tk
import time
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import shutil
import os
from app import ClipSorterApp

# Skip GUI tests if display is not available
def is_gui_available():
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except (tk.TclError, Exception):
        return False

pytestmark = pytest.mark.skipif(not is_gui_available(), reason="No display available for GUI tests")

@pytest.fixture
def app_instance():
    # Mock dependency check to avoid blocking dialogs on systems without ffmpeg
    with patch('app.check_all_dependencies', return_value=[]):
        app = ClipSorterApp()
        yield app
        # Clean up after test - use the official closure logic to handle threads
        if app.root.winfo_exists():
            app._on_close()

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)

def wait_for_idle(app: ClipSorterApp, timeout=5):
    """Run the Tk event loop until idle or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        app.root.update()
        time.sleep(0.05)

def test_initial_state(app_instance: ClipSorterApp):
    app = app_instance
    # Ensure welcome view doesn't block initial check if it's there
    if hasattr(app, 'main_container'):
        app.root.update()
    
    assert str(app.run_button["state"]) == "disabled"
    assert str(app.preview_button["state"]) == "disabled"
    assert str(app.cancel_button["state"]) == "disabled"
    assert app.progress_var.get() == 0

def test_button_enable_on_valid_path(app_instance: ClipSorterApp, temp_dir: Path):
    app = app_instance
    
    # Simulate valid folder
    app.folder_entry.insert(0, str(temp_dir))
    app._validate_folder()
    
    assert str(app.run_button["state"]) == "normal"
    assert str(app.preview_button["state"]) == "normal"

def test_dry_run_integration(app_instance: ClipSorterApp, temp_dir: Path):
    app = app_instance
    # Create dummy files
    for i in range(2):
        (temp_dir / f"test{i}.jpg").touch()
        
    app.folder_entry.insert(0, str(temp_dir))
    app.dry_run_var.set(True) # Check the "Preview only" box
    app._validate_folder()
    
    with patch('app.MediaPipelineService.run', return_value={"status": "success"}) as mock_run:
        app.run_button.invoke() # Start pipeline using Run button
        
        wait_for_idle(app)
        
        assert mock_run.called
        # Verify dry_run was passed because the checkbox was set
        assert app.service.dry_run is True

def test_cancel(app_instance: ClipSorterApp, temp_dir: Path):
    app = app_instance
    app.folder_entry.insert(0, str(temp_dir))
    app._validate_folder()
    
    # Mock service so we can control events
    with patch('app.MediaPipelineService') as MockService:
        instance = MockService.return_value
        app.run_button.invoke() # This will call _start_pipeline which instantiates MockService
        
        # Verify it started
        assert app.service is not None
        
        # Trigger cancel
        app.cancel_button.invoke()
        assert instance.cancel.called
        assert app.status_var.get() == "Cancelling..."
        
        # Simulate 'cancelled' event coming back from service
        app._handle_event({"event": "cancelled"})
        
        wait_for_idle(app)
        assert app.status_var.get() == "Cancelled"

def test_keyboard_shortcuts(app_instance: ClipSorterApp, temp_dir: Path):
    app = app_instance
    app.folder_entry.insert(0, str(temp_dir))
    app._validate_folder()
    app.root.focus_force()
    app.root.update()
    
    with patch('app.MediaPipelineService.run', return_value={"status": "success"}) as mock_run:
        app.root.event_generate("<Control-Return>")
        app.root.update()
        time.sleep(0.1)
        assert mock_run.called
        
    with patch('app.MediaPipelineService.run', return_value={"status": "success"}) as mock_run:
        app.root.event_generate("<Shift-Return>")
        app.root.update()
        time.sleep(0.1)
        assert mock_run.called
