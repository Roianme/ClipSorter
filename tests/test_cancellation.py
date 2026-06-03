"""Test cancellation support in the pipeline."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from pipeline_shared import CancellationToken
from sort_photo import sort_photo
from PIL import Image

def test_pipeline_cancellation(tmp_path: Path) -> None:
    source = tmp_path / "TargetFolder"
    source.mkdir()

    # Create several files to make the process take longer
    for i in range(10):
        photo = source / f"photo_{i}.jpg"
        Image.new("RGB", (100, 100)).save(photo)

    token = CancellationToken()
    
    # Run the pipeline in a separate thread
    def run():
        # Pass the token
        sort_photo(source, cancel_token=token)

    thread = threading.Thread(target=run)
    thread.start()

    # Give it a moment to start
    time.sleep(0.5)
    
    # Cancel the pipeline
    token.cancel()
    
    thread.join(timeout=5)
    
    assert not thread.is_alive(), "Pipeline should have finished after cancellation"
    
    # Check that it did not complete successfully by checking for output
    output = tmp_path / "TargetFolder_sorted"
    # It might create the folder, but shouldn't have a report or complete successfully
    # Actually, the requirement says "Not write a final report file"
    assert not (output / "_report.txt").exists(), "Report should not have been created"
