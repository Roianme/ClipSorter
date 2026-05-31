"""Integration tests for sort.py (Step 11)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import sort
from PIL import Image


def test_sort_cli_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "TargetFolder"
    source.mkdir()

    photo = source / "photo.jpg"
    image = Image.new("RGB", (100, 100))
    pixels = image.load()
    for y in range(100):
        for x in range(100):
            value = 255 if ((x // 10 + y // 10) % 2 == 0) else 0
            pixels[x, y] = (value, value, value)
    image.save(photo)

    unsupported = source / "notes.txt"
    unsupported.write_text("not media")

    script = Path(__file__).resolve().parents[1] / "sort.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"STDERR: {result.stderr}"
    assert "ClipSorter v1.0" in result.stdout
    assert "Report saved to:" in result.stdout

    output = tmp_path / "TargetFolder_sorted"
    assert output.is_dir()
    assert (output / "defects" / "photos" / "photo.jpg").is_file()

    report = output / "_report.txt"
    assert report.is_file()
    report_text = report.read_text(encoding="utf-8")
    assert "Total files found:" in report_text
    assert "Files skipped:" in report_text
    assert "DETAIL LOG" in report_text
    assert "[SKIPPED]" in report_text


def test_run_qc_check_uses_image_array_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    record = {
        "converted_path": "dummy.jpg",
        "detected_type": "photo",
        "image_array": object(),
    }
    config: dict[str, object] = {}
    called: dict[str, object] = {}

    def fake_analyze_photo(*args: object, **kwargs: object) -> dict[str, object]:
        called["args"] = args
        called["kwargs"] = kwargs
        return {
            "duration_check": "pass",
            "blur_check": "pass",
            "exposure_check": "pass",
            "shake_check": "pass",
            "reasons": [],
        }

    monkeypatch.setattr(sort, "analyze_photo", fake_analyze_photo)

    converted_path, qc_result = sort._run_qc_check(record, config)

    assert converted_path == "dummy.jpg"
    assert qc_result["duration_check"] == "pass"
    assert called["kwargs"]["frame"] is record["image_array"]
