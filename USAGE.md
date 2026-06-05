# ClipSorter Usage Guide

ClipSorter is a non-destructive QC sorting tool for raw media folders. It scans your media, converts it to standard formats, runs quality checks, and organizes the results into a new folder.

## Getting Started

1.  **Prepare your media:** Place your raw photos, videos, or audio files in a folder (e.g., `C:\MyRawMedia`).
2.  **Run ClipSorter:** Open a terminal and run the tool pointing to that folder:
    ```bash
    python sort.py all "C:\MyRawMedia"
    ```
3.  **Check the Results:** A new folder named `C:\MyRawMedia_sorted` will be created. Inside, you'll find your files **renamed and organized** into subfolders, along with a summary report.

## Installation

```bash
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install dependencies (if needed)
pip install -r requirements.txt
```

## Desktop GUI

For a visual experience, run the desktop application:

```bash
python app.py
```

## Basic Usage (CLI)

### Sort Photos Only
```bash
python sort.py photo "C:\Path\To\Media"
```
Processes `.jpg`, `.png`, `.arw`, etc. Includes burst detection.

### Sort Videos Only
```bash
python sort.py video "C:\Path\To\Media"
```
Processes `.mp4`, `.mov`, `.mxf`, etc. Includes steady-shot detection.

### Sort Audio Only
```bash
python sort.py audio "C:\Path\To\Media"
```
Processes `.mp3`, `.wav`, etc. Includes silence detection.

### Sort All Media Types
```bash
python sort.py all "C:\Path\To\Media"
```
Runs all pipelines sequentially.

## Expected Outputs

When you run ClipSorter on a folder (e.g., `MyMedia`), it creates a **sibling folder** named `MyMedia_sorted`. The original folder remains completely untouched.

### Output Folder Structure

```
MyMedia_sorted/
├── _report.txt         (Human-readable summary of every decision)
├── review/             (Files that passed QC or need minor review)
│   ├── photos/
│   ├── videos/
│   ├── audio/
│   └── burst/          (Burst photo groups, non-representatives)
└── defects/            (Files that failed quality checks)
    ├── photos/
    ├── videos/
    └── audio/
```

### Bucket Definitions

*   **review/**: This is your primary output. It contains "Clean" files that passed all quality checks, and files that are usable but might benefit from a quick look (e.g., slightly shaky video or suspected duplicates).
*   **defects/**: Files that failed significant quality checks. This includes very blurry photos, extremely underexposed/overexposed media, or silent audio clips.
*   **burst/** (Photos only): When a burst of photos is detected, the best shot is moved to `review/photos`, and the rest are placed in `review/burst` to keep your main gallery clean while preserving all shots.

### File Renaming Mechanics

To keep your sorted media organized and easily searchable, ClipSorter automatically renames every file moved to the output folder.

**The Naming Pattern:**
`[SourceFolderName]_[MediaType]_[SequenceNumber].[Extension]`

*   **Source Folder Name**: The name of the root folder you selected (e.g., `MyMedia`).
*   **Media Type**: The detected type of the file (`photo`, `video`, or `audio`).
*   **Sequence Number**: A 4-digit counter starting at `0001` that increments for every file processed in the current run.
*   **Extension**: The canonical extension for that media type (`.jpg`, `.mp4`, or `.mp3`).

**Example:**
If sorting a folder named `Vacation`, the first photo moved will be `Vacation_photo_0001.jpg`.

**Collision Handling:**
ClipSorter is designed to be safe. If a file with the generated name already exists in the destination folder (for example, if you run the tool multiple times on the same output folder), it will append a unique suffix like `_1`, `_2`, etc., to prevent overwriting any existing data.

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
- Creates a comprehensive text report (`_report.txt`) with a full pipeline summary
- Includes file-by-file analysis, QC results, and original file paths

## Report Output

Each run generates a detailed report named `_report.txt` in the root of the output folder:

```text
========================================
CLIPSORTER REPORT
Run date: 2026-06-01 14:23:45
Source folder: C:\MyMedia
Output folder: C:\MyMedia_sorted
========================================

SUMMARY
-------
Total files found:        150
Files processed:          145
Files skipped:            5  (unsupported type)

Converted to mp4:         10
Converted to jpg:         135
Converted to mp3:         0

Results:
  Review:                 132
  Defects:                 13

========================================
DETAIL LOG
========================================

[REVIEW]   photos/MyMedia_photo_0001.jpg
           Original: /original/IMG_001.jpg
           Converted from: .jpg (no conversion needed)
           Duration: PASS | Blur: PASS | Exposure: PASS

[DEFECTS]  photos/MyMedia_photo_0015.jpg
           Original: /original/IMG_0015.jpg
           Blur: REJECTED (Laplacian variance: 12.4, threshold: 80.0)

...
========================================
END OF REPORT
========================================
```

## Examples

### Workflow 1: Process Only Photos

```bash
# Sort photos from a folder
python sort.py photo "C:\Media\2024_Events"

# Check results in the report
# Output: C:\Media\2024_Events_sorted\_report.txt
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

# View summary results at the end of the run
# Check D:\Raw_Media_sorted\_report.txt for details
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
