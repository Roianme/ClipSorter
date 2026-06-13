"""Integration tests for sort.py (Step 11)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

# Ensure src is in path for imports
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sort
import pipeline_shared


def test_sort_cli_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "TargetFolder"
    source.mkdir()

    # Create a small valid JPEG
    photo = source / "photo.jpg"
    image = Image.new("RGB", (100, 100))
    image.save(photo)

    unsupported = source / "notes.txt"
    unsupported.write_text("not media")

    # Mock the classifier to avoid heavy YOLO model loading
    with patch("classifier.classify_file") as mock_classify:
        mock_classify.return_value = {
            "blur_check": "pass",
            "exposure_check": "pass",
            "shake_check": "pass",
            "reasons": []
        }
        
        # Mock sys.argv for the CLI call
        test_args = ["sort.py", "photo", str(source)]
        monkeypatch.setattr(sys, "argv", test_args)
        
        # Run main and catch SystemExit
        try:
            from cli import main
            exit_code = main()
        except SystemExit as e:
            exit_code = e.code

        assert exit_code == 0

    output = tmp_path / "TargetFolder_sorted"
    assert output.is_dir()
    # In single-type mode, files go directly into bucket folders
    # Note: filename might change due to allocation logic
    assert any(output.glob("defects/*.jpg"))

    report = output / "_report.txt"
    assert report.is_file()
    report_text = report.read_text(encoding="utf-8")
    assert "Total files found:" in report_text
    assert "Files processed:" in report_text


def test_run_qc_check_wrapper_uses_image_array_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    record = {
        "converted_path": "dummy.jpg",
        "detected_type": "photo",
        "image_array": object(),
    }
    config: dict[str, object] = {}
    
    def fake_analyze_photo(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "duration_check": "pass",
            "blur_check": "pass",
            "exposure_check": "pass",
            "shake_check": "pass",
            "reasons": [],
            "frame": kwargs.get("frame")
        }

    qc_functions = {"photo": fake_analyze_photo}
    converted_path, qc_result = pipeline_shared.run_qc_check_wrapper(record, config, qc_functions)

    assert converted_path == "dummy.jpg"
    assert qc_result["duration_check"] == "pass"
    assert qc_result["frame"] is record["image_array"]
