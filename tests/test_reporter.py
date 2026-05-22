"""Tests for reporter (Step 10)."""

from __future__ import annotations

from pathlib import Path

from reporter import write_report


def test_write_report_creates_report_file(tmp_path: Path) -> None:
    output_folder = tmp_path / "TargetFolder_sorted"
    output_folder.mkdir()

    report_data = {
        "run_date": "2026-05-22 12:00:00",
        "source_folder": "/tmp/source",
        "output_folder": str(output_folder),
        "total_files_found": 3,
        "files_processed": 2,
        "files_skipped": 1,
        "skipped_note": "unsupported type",
        "converted_counts": {"mp4": 1, "jpg": 1, "mp3": 0},
        "results": {"clean": 1, "review": 1, "rejected": 0},
        "entries": [
            {
                "bucket": "clean",
                "final_path": "videos/clip.mp4",
                "original_path": "/source/clip.mov",
                "converted_from": ".mov",
                "metadata": {
                    "Duration": "12.3s",
                    "Blur": "PASS",
                    "Exposure": "PASS",
                    "Shake": "PASS",
                },
                "flags": [],
            },
            {
                "bucket": "skipped",
                "final_path": "/documents/brief.pdf",
                "original_path": "/documents/brief.pdf",
                "reason": "Unsupported file type",
            },
        ],
    }

    report_path = write_report(output_folder, report_data)

    assert report_path == output_folder / "_report.txt"
    assert report_path.is_file()

    content = report_path.read_text(encoding="utf-8")
    assert "CLIPSORTER REPORT" in content
    assert "Run date: 2026-05-22 12:00:00" in content
    assert "Source folder: /tmp/source" in content
    assert "Output folder: " in content
    assert "SUMMARY" in content
    assert "DETAIL LOG" in content
    assert "END OF REPORT" in content
    assert "[CLEAN]    videos/clip.mp4" in content
    assert "Converted from: .mov" in content
    assert "[SKIPPED]  /documents/brief.pdf" in content
    assert "Reason: Unsupported file type" in content


def test_write_report_includes_summary_counts(tmp_path: Path) -> None:
    output_folder = tmp_path / "out"
    output_folder.mkdir()

    report_data = {
        "run_date": "2026-05-22 13:00:00",
        "source_folder": "/tmp/source",
        "output_folder": str(output_folder),
        "total_files_found": 5,
        "files_processed": 4,
        "files_skipped": 1,
        "skipped_note": "unsupported type",
        "converted_counts": {"mp4": 2, "jpg": 1, "mp3": 1},
        "results": {"clean": 2, "review": 1, "rejected": 1},
        "entries": [],
    }

    report_path = write_report(output_folder, report_data)
    contents = report_path.read_text(encoding="utf-8")

    assert "Total files found:        5" in contents
    assert "Files processed:          4" in contents
    assert "Files skipped:            1  (unsupported type)" in contents
    assert "Converted to mp4:         2" in contents
    assert "Converted to jpg:         1" in contents
    assert "Converted to mp3:         1" in contents
    assert "Clean:" in contents
    assert "Review:" in contents
    assert "Rejected:" in contents
