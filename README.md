# ClipSorter

ClipSorter is a professional, non-destructive QC sorting tool for raw media folders. It is designed for news producers and video editors who need to quickly organize large volumes of raw media (photos, videos, and audio) before starting their edit.

### 📥 [Download Latest Release (v1.0.0-beta)](https://github.com/Roianme/ClipSorter/releases/tag/v1.0.0-beta)

## Key Features

- **Non-Destructive:** Your original folder is never modified or deleted.
- **Auto-Conversion:** Normalizes all media to canonical formats (`.jpg`, `.mp4`, `.mp3`).
- **Quality Control (QC):** Automatically identifies blurry photos, shaky video, silent audio, and exposure issues.
- **Smart Sorting:** Groups files into `review/` and `defects/` buckets based on QC results.
- **Burst Detection:** Identifies photo bursts and picks the best shot for your main gallery.
- **Duplicate Detection:** Finds and flags content-level duplicates across your media.
- **Detailed Reporting:** Generates a comprehensive report of every decision made during the sort.

## Getting Started

To get started with ClipSorter, please see the [Usage Guide](USAGE.md).

### Quick Start (CLI)

```bash
python sort.py all "path/to/your/media"
```

### Quick Start (GUI)

```bash
python app.py
```

## Documentation

- [User Installation Guide](USER_GUIDE.md) - Beginner-friendly guide for downloading and running the app.
- [Usage Guide](USAGE.md) - Detailed technical instructions and expected outputs.
- [Optimization Guide](OPTIMIZATION_GUIDE.md) - Tips for large datasets.
