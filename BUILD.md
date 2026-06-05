# ClipSorter Build Instructions

## Media Conversion Logic

ClipSorter uses a unified conversion process to prepare media files for sorting, ensuring all files are in a "canonical" format for consistent processing.

- **Photos**:
    - **Standard formats (JPG, PNG, TIFF, etc.)**: Converted to high-quality JPEG using Pillow.
    - **RAW files (ARW, CR2, NEF, etc.)**: Processed using `rawpy` to post-process into JPEG. If processing fails or is slow (exceeding configured timeout), it attempts to extract the embedded JPEG preview.
- **Videos**:
    - **H.264/AVC (MP4/MOV)**: If already in H.264, the stream is copied directly for speed (no re-encoding).
    - **Other formats**: Re-encoded to MP4 using `ffmpeg` with configured codec and CRF settings.
- **Audio**:
    - Converted to MP3 using `ffmpeg` and `libmp3lame` based on the configured bitrate.

All converted files are placed in a temporary working directory (`clipsorter_work` in system temp) before classification and final sorting.

## Expected Output

After sorting, ClipSorter creates an output folder (e.g., `TargetFolder_sorted/`) containing:
- **`review/`**: Contains sorted media that are good or require a quick look (e.g., duplicates to decide on, burst shots).
- **`defects/`**: Contains media that failed quality checks (blurry, defective, etc.).
- **`_report.txt`**: A detailed summary of the sorting operation, including counts of processed/skipped files, duplicates found, and moved items.

## Building Executables

This project uses [PyInstaller](https://pyinstaller.org/) to create standalone executables.

### Prerequisites

1.  **Install requirements**:
    ```bash
    pip install -r requirements.txt
    pip install pyinstaller
    ```

2.  **Build**:
    Run the following command from the project root:
    ```bash
    pyinstaller clipSorter.spec
    ```

The executables will be generated in the `dist/` directory.

## Running Tests

### Pipeline Tests
```bash
pytest tests/
```

### GUI Tests
GUI tests require a graphical display environment.
- **Windows/macOS**: Just run `pytest tests/test_gui.py`.
- **Linux**: Run using a virtual display:
  ```bash
  xvfb-run pytest tests/test_gui.py
  ```

## CI/CD Notes
For future CI integration (e.g., GitHub Actions), use a runner with a display (e.g., `ubuntu-latest` with `xvfb`) to execute the GUI tests automatically.
