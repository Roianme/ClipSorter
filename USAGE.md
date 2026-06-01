# ClipSorter Usage Guide

ClipSorter supports separate sorting of **photos**, **videos**, and **audio** files as independent instances. You can process each media type separately or together.

## Installation

```bash
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install dependencies (if needed)
pip install -r requirements.txt
```

## Basic Usage

### Sort Photos Only

```bash
python sort.py photo "E:\DMM Aus\chron sg\110D7000"
```

Processes only `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.webp` files.

**Features for photos:**
- Burst group detection and representative selection
- Blur and exposure QC checks
- Photo-specific duplicate detection

### Sort Videos Only

```bash
python sort.py video "E:\DMM Aus\chron sg\110D7000"
```

Processes only `.mp4`, `.mov`, `.mxf`, `.avi`, `.mkv`, `.wmv`, `.mts`, `.m2ts`, `.3gp`, `.flv`, `.webm`, `.ts`, `.vob` files.

**Features for videos:**
- Steady shot QC checks
- Video-specific duplicate detection

### Sort Audio Only

```bash
python sort.py audio "E:\DMM Aus\chron sg\110D7000"
```

Processes only `.mp3`, `.m4a`, `.aac`, `.flac`, `.wav`, `.wma`, `.ogg` files.

**Features for audio:**
- Silence detection QC checks
- Audio-specific duplicate detection

### Sort All Media Types

```bash
python sort.py all "E:\DMM Aus\chron sg\110D7000"
```

Runs all three sorting pipelines sequentially:
1. Photo sorting
2. Video sorting
3. Audio sorting

Each completes with its own report.

## Advanced Options

### With Custom Config

```bash
python sort.py photo "E:\DMM Aus\chron sg\110D7000" --config custom_config.json
```

### With Verbose Output

```bash
python sort.py video "E:\DMM Aus\chron sg\110D7000" --verbose
```

Shows debug-level logging for troubleshooting.

### Combined Options

```bash
python sort.py audio "E:\DMM Aus\chron sg\110D7000" --config custom.json --verbose
```

## Output Structure

Each run creates organized output in the source folder:

```
source_folder/
├── usable/
│   ├── photo/      (high-quality photos)
│   ├── video/      (high-quality videos)
│   └── audio/      (high-quality audio)
├── defects/
│   ├── photo/      (photos with issues)
│   ├── video/      (videos with issues)
│   └── audio/      (audio with issues)
├── burst/          (burst photo groups, only from photo run)
├── duplicates/     (duplicate files)
└── reports/
    └── report_TIMESTAMP.json
```

## Pipeline Stages (Per Media Type)

### 1. Scanning
- Identifies supported files by media type
- Filters out unsupported formats

### 2. Format Conversion
- Converts files to standard format:
  - Photos → `.jpg`
  - Videos → `.mp4`
  - Audio → `.mp3`

### 3. Quality Checks (QC)
**Photos:**
- Blur detection
- Exposure analysis

**Videos:**
- Duration validation
- Steady shot detection (5-second window analysis)

**Audio:**
- Duration validation
- Silence detection

### 4. Duplicate Detection
- Finds duplicate files per media type
- Marks duplicates for removal

### 5. Burst Detection (Photos Only)
- Groups consecutive photos (burst mode)
- Selects best photo from each burst based on QC scores

### 6. Classification
- Assigns to bucket: `usable`, `defects`, `duplicate`, or `burst`

### 7. File Moving
- Moves converted files to appropriate folders
- Organizes by quality and type

### 8. Report Generation
- Creates JSON report with full pipeline summary
- Includes file-by-file analysis and QC results

## Report Output

Each run generates a timestamped JSON report in `reports/`:

```json
{
  "run_date": "2026-06-01 14:23:45",
  "media_type": "photo",
  "source_folder": "E:\\DMM Aus\\chron sg\\110D7000",
  "output_folder": "E:\\DMM Aus\\chron sg\\110D7000",
  "total_files_found": 150,
  "files_processed": 145,
  "files_skipped": 5,
  "converted_counts": {"jpg": 145},
  "results": {
    "usable": 132,
    "defects": 13
  },
  "entries": [
    {
      "bucket": "usable",
      "final_path": "usable/photo/IMG_001.jpg",
      "original_path": "/original/IMG_001.jpg",
      "converted_from": ".jpg (no conversion needed)",
      "metadata": {
        "Duration": "PASS",
        "Blur": "PASS",
        "Exposure": "PASS"
      },
      "flags": []
    },
    ...
  ]
}
```

## Examples

### Workflow 1: Process Only Photos

```bash
# Sort photos from a folder
python sort.py photo "C:\Media\2024_Events"

# Check results in the report
# Output: C:\Media\2024_Events\reports\report_*.json
```

### Workflow 2: Separate Processing by Type

```bash
# First, handle photos (includes burst detection)
python sort.py photo "D:\Raw_Media"

# Later, handle videos separately
python sort.py video "D:\Raw_Media"

# Finally, handle audio
python sort.py audio "D:\Raw_Media"
```

### Workflow 3: Batch Process Everything

```bash
# Process all media types at once
python sort.py all "D:\Raw_Media" --verbose

# View results
cd D:\Raw_Media\reports
type report_*.json | findstr "usable\|defects"
```

### Workflow 4: Use Custom Settings

```bash
# With custom config for stricter QC
python sort.py photo "F:\Archive" --config strict_qc.json

# With verbose output for debugging
python sort.py video "F:\Archive" --verbose

# Both combined
python sort.py audio "F:\Archive" --config custom.json --verbose
```

## Advantages of Separate Processing

✅ **Parallelizable** - Run photo, video, audio jobs simultaneously on different cores  
✅ **Incremental** - Process one media type at a time  
✅ **Flexible** - Skip media types you don't need  
✅ **Cleaner Reports** - Each report focuses on one media type  
✅ **Media-Specific QC** - Different quality checks per type  
✅ **Easier Debugging** - Troubleshoot one pipeline at a time  

## Configuration

See `config.json` for adjustable parameters:

```json
{
  "conversion_parallel_workers": 4,
  "qc_parallel_workers": 2,
  "photo_blur_threshold": 0.7,
  "video_steady_threshold": 0.8,
  "audio_silence_threshold": 0.1
}
```

## Troubleshooting

### "File not found" errors
- Ensure path exists and is accessible
- Use full paths, not relative paths
- Check folder permissions

### Long running times
- Reduce `conversion_parallel_workers` if system is slow
- Process media types separately instead of `all`

### Quality check failures
- Review thresholds in `config.json`
- Use `--verbose` flag to see detailed QC analysis
- Check `defects/` folder for borderline files

## Help

```bash
python sort.py -h
```

Shows available commands and options.
