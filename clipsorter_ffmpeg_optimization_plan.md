# ClipSorter — FFmpeg Optimization: Agent Execution Plan
## HandBrake-Inspired Lightweight Build

**Target:** Reduce multimedia binary footprint from ~450 MB → under 20 MB (Phase A), or near-zero (Phase B via PyAV).  
**Philosophy:** "Enable nothing. Add only what you use." — same principle HandBrake uses internally.

---

## Pre-Work: Read Before Touching Any Code

Before writing a single line, understand the two-phase strategy:

- **Phase A (Immediate):** Keep the subprocess architecture (`ffmpeg`/`ffprobe` as external binaries), but replace the bloated full-build with a custom minimal static build. Drop-in replacement. Low risk.
- **Phase B (Next major iteration):** Replace all subprocess calls with PyAV — the actual HandBrake pattern. Embeds the codec libraries directly into Python. No external executables at all.

Execute Phase A completely before beginning Phase B.

---

## Git Strategy: Branching and Commit Rules

### Rule 1 — Never work on `main` directly

Before touching a single file, create a feature branch:

```bash
git checkout -b feature/ffmpeg-optimization
```

Phase A lives entirely on this branch. Phase B gets its own separate branch later:

```bash
git checkout -b feature/pyav-integration   # only when Phase A is merged and stable
```

### Rule 2 — Commit at these specific checkpoints only

Do not commit after every file edit. Commit at the natural boundaries listed below. Each commit should leave the codebase in a working, non-broken state.

| Commit | When to commit | Suggested message |
|--------|---------------|-------------------|
| **C1** | After Step 1 — audit table complete | `audit: document minimum codec/format requirements for ffmpeg build` |
| **C2** | After Steps 2 + 3 — binary_resolver written and all hardcoded strings replaced | `refactor: add binary_resolver.py and remove hardcoded binary paths` |
| **C3** | After Steps 4 + 5 — build script written and binaries verified locally | `build: add minimal ffmpeg build script and verified dist binaries` |
| **C4** | After Steps 6 + 7 — PyInstaller spec updated and missing-binary dialog added | `packaging: update spec and add missing-binary startup dialog` |
| **C5** | After Step 8 — all validation checks pass | `chore: Phase A validation complete — all smoke tests passing` |
| **C6** *(Phase B)* | After Steps 9 + 10 — all subprocess calls replaced with PyAV | `refactor: replace ffmpeg/ffprobe subprocess calls with PyAV` |
| **C7** *(Phase B)* | After Step 11 — custom PyAV wheel built and packaged | `build: link PyAV against minimal custom FFmpeg, eliminate bundled full build` |

### Rule 3 — Never commit compiled binaries to Git

The built `ffmpeg` and `ffprobe` binaries must never be committed to the repository. Add the following to `.gitignore` before Step 4:

```
# FFmpeg build artifacts — never commit binaries
ffmpeg_src/
scripts/dist/
*.exe
ffmpeg
ffprobe
pyav_src/build/
```

Store built binaries as GitHub Release assets, S3 objects, or CI pipeline artifacts. Your build/packaging script should download them at build time, not check them in.

### Rule 4 — Open a PR into `main` only after C5

Do not merge into `main` until all Step 8 validation checks are green. The PR description should include the before/after binary size numbers as evidence.

---

## PHASE A — Custom Minimal FFmpeg Binaries

---

### Step 1 — Exhaustive Codebase Audit (DO THIS FIRST, DO NOT SKIP)

The custom FFmpeg build will use `--disable-everything`. A single missing codec or demuxer will silently break a pipeline function. This audit is the foundation of everything.

**1.1 — Grep for all subprocess invocations**

Run the following searches across the entire repo:

```bash
# Find all ffprobe calls
grep -rn "ffprobe" --include="*.py" .

# Find all ffmpeg calls
grep -rn "ffmpeg" --include="*.py" .

# Find any shell=True calls that might hide binary names
grep -rn "subprocess" --include="*.py" .
grep -rn "Popen\|check_output\|run(" --include="*.py" .
```

**1.2 — For each invocation, record the following in a checklist:**

| File | Function | Binary | Flags Used | Input Formats | Output Format |
|------|----------|--------|------------|---------------|---------------|
| src/converter.py | `_video_codec_name` | ffprobe | `-show_streams -select_streams v` | any | — |
| src/converter.py | `_video_resolution` | ffprobe | `-show_streams -select_streams v` | any | — |
| src/qc_video.py | `_run_ffprobe_duration_seconds` | ffprobe | `-show_entries format=duration` | any | — |
| src/converter.py | (HEVC transcode) | ffmpeg | `-c:v libx264 -pix_fmt yuv420p` | HEVC/H.265 | MP4 |
| src/converter.py | (format normalization) | ffmpeg | `-c:v libx264 -c:a aac` | AVI/MOV/MTS/MP4 | MP4 |
| src/converter.py | (1080p rescale) | ffmpeg | `-vf scale=-2:1080 -pix_fmt yuv420p` | 4K+ | MP4 |

> Fill in any rows not listed above from your grep results. Do not proceed to Step 2 until this table is complete.

**1.3 — From the audit, derive the minimum component list:**

Confirm or extend this list based on your actual findings:

```
DECODERS:    h264, hevc, aac, mp3, pcm_s16le, pcm_s24le
ENCODERS:    libx264, aac
DEMUXERS:    mov,mp4,m4a,3gp,3g2,mj2  matroska,webm  avi  mpegts  mpeg  wav
MUXERS:      mp4
PARSERS:     h264, hevc, aac, mpegaudio
FILTERS:     scale, format
PROTOCOLS:   file  [add "pipe" if any subprocess uses stdin/stdout pipes]
BSF:         h264_mp4toannexb, hevc_mp4toannexb
```

> ⚠️ If your source clips include MPEG-2 video (common in legacy `.mts` files from older cameras), add `decoder=mpeg2video` and `parser=mpegvideo`. Check your test corpus.

> 📌 **COMMIT C1 — Before proceeding to Step 2**
> The audit table and component list must be finalized and committed. This is the reference document for every build decision that follows.
> ```bash
> git add docs/audit_checklist.md   # or wherever you saved the table
> git commit -m "audit: document minimum codec/format requirements for ffmpeg build"
> ```

---

### Step 2 — Write `src/binary_resolver.py`

Create this new file. It replaces all hardcoded binary path logic across the project.

```python
# src/binary_resolver.py
"""
Priority chain for resolving ffmpeg/ffprobe paths:
  1. Environment variable override (for CI, Docker, power users)
  2. Bundled binary alongside the executable (thin-bundle mode)
  3. System PATH (for users who have FFmpeg installed natively)
Raises FileNotFoundError with a clear, actionable message if not found.
"""
import shutil
import sys
import os

FFMPEG_ENV_KEY = "CLIPSORTER_FFMPEG_PATH"
FFPROBE_ENV_KEY = "CLIPSORTER_FFPROBE_PATH"

_cache: dict[str, str] = {}


def resolve_binary(name: str) -> str:
    """Return the absolute path to 'ffmpeg' or 'ffprobe'."""
    if name in _cache:
        return _cache[name]

    env_key = FFMPEG_ENV_KEY if name == "ffmpeg" else FFPROBE_ENV_KEY

    # Priority 1: Explicit env override
    env_path = os.environ.get(env_key)
    if env_path and os.path.isfile(env_path):
        _cache[name] = env_path
        return env_path

    # Priority 2: Bundled next to executable (PyInstaller extracts to _MEIPASS)
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    suffix = ".exe" if sys.platform == "win32" else ""
    bundled = os.path.join(base_dir, name + suffix)
    if os.path.isfile(bundled):
        _cache[name] = bundled
        return bundled

    # Priority 3: System PATH
    system_path = shutil.which(name)
    if system_path:
        _cache[name] = system_path
        return system_path

    raise FileNotFoundError(
        f"'{name}' was not found on this system.\n"
        f"  Option 1: Install FFmpeg from https://ffmpeg.org/download.html\n"
        f"  Option 2: Set the environment variable {env_key} to the full path of {name}."
    )


def check_all_dependencies() -> list[str]:
    """Returns a list of binary names that are missing. Empty list = all OK."""
    missing = []
    for binary in ["ffmpeg", "ffprobe"]:
        try:
            resolve_binary(binary)
        except FileNotFoundError:
            missing.append(binary)
    return missing
```

---

### Step 3 — Refactor All Binary Calls to Use `binary_resolver`

**3.1 — In `src/converter.py`:**

Find every place that constructs an ffmpeg/ffprobe command. Replace the binary name at the start of the command list.

Before:
```python
cmd = ["ffprobe", "-v", "quiet", "-show_streams", ...]
cmd = ["ffmpeg", "-i", input_path, "-c:v", "libx264", ...]
```

After:
```python
from binary_resolver import resolve_binary

cmd = [resolve_binary("ffprobe"), "-v", "quiet", "-show_streams", ...]
cmd = [resolve_binary("ffmpeg"), "-i", input_path, "-c:v", "libx264", ...]
```

**3.2 — In `src/qc_video.py`:**

Same pattern. Every `"ffprobe"` string at the head of a subprocess call becomes `resolve_binary("ffprobe")`.

**3.3 — Search for any other occurrences:**

```bash
grep -rn '"ffmpeg"\|"ffprobe"\|ffmpeg.exe\|ffprobe.exe' --include="*.py" .
```

Every match must be replaced. Zero hardcoded binary strings should remain after this step.

> 📌 **COMMIT C2 — After Step 3 verification grep returns zero results**
> This commit is pure Python — no binaries, no build artifacts. It is independently revertable if something breaks.
> ```bash
> git add src/binary_resolver.py src/converter.py src/qc_video.py
> git commit -m "refactor: add binary_resolver.py and remove hardcoded binary paths"
> ```

---

### Step 4 — Build Minimal FFmpeg from Source (Linux/macOS)

> **Prerequisites:** `gcc`, `make`, `nasm`, `yasm`, `pkg-config`, `libx264-dev` (or build x264 from source for a fully static result).

**4.1 — Clone FFmpeg source:**

```bash
git clone --depth 1 --branch release/6.1 https://git.ffmpeg.org/ffmpeg.git ffmpeg_src
cd ffmpeg_src
```

**4.2 — Run configure with the minimal flag set:**

```bash
./configure \
  --prefix="$(pwd)/dist" \
  \
  --disable-everything \
  --disable-avdevice \
  --disable-postproc \
  --disable-doc \
  --disable-htmlpages \
  --disable-manpages \
  --disable-podpages \
  --disable-txtpages \
  --disable-debug \
  --disable-ffplay \
  \
  --enable-avcodec \
  --enable-avformat \
  --enable-avutil \
  --enable-swresample \
  --enable-swscale \
  --enable-avfilter \
  \
  --enable-small \
  --enable-gpl \
  --enable-libx264 \
  \
  --enable-decoder=h264,hevc,aac,mp3,pcm_s16le,pcm_s24le \
  --enable-encoder=libx264,aac \
  --enable-demuxer=mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,mpegts,mpeg,wav \
  --enable-muxer=mp4 \
  --enable-parser=h264,hevc,aac,mpegaudio \
  --enable-filter=scale,format \
  --enable-protocol=file \
  --enable-bsf=h264_mp4toannexb,hevc_mp4toannexb \
  \
  --pkg-config-flags="--static" \
  --extra-ldflags="-static" \
  --extra-libs="-lpthread -lm" \
  --extra-cflags="-Os" \
  \
  --enable-ffmpeg \
  --enable-ffprobe
```

> ⚠️ **Critical note:** Do NOT use `--disable-programs` — this would prevent `ffprobe` from being built. Instead, explicitly disable only `ffplay` with `--disable-ffplay`. The `--enable-ffmpeg` and `--enable-ffprobe` flags are the default when programs are enabled, but listing them explicitly is clearer.

> If you added `mpeg2video` to your decoder list in Step 1.3, add `--enable-decoder=mpeg2video` and `--enable-parser=mpegvideo` here.

**4.3 — Build:**

```bash
make -j$(nproc)
make install
```

**4.4 — Strip debug symbols:**

```bash
strip dist/bin/ffmpeg dist/bin/ffprobe
```

**4.5 — (Optional) UPX compression for additional 30–50% size reduction:**

```bash
# Install: apt install upx / brew install upx
upx --best --lzma dist/bin/ffmpeg dist/bin/ffprobe
```

> ⚠️ UPX-compressed binaries can trigger false positives in some Windows AV scanners. Test on Windows before shipping. Skip for Windows builds if this is a concern.

**4.6 — Verify the output:**

```bash
ls -lh dist/bin/ffmpeg dist/bin/ffprobe
# Expected: ffmpeg ~8–15 MB, ffprobe ~4–8 MB

./dist/bin/ffmpeg -version
./dist/bin/ffprobe -version
./dist/bin/ffmpeg -codecs 2>/dev/null | grep -E "h264|hevc|aac"
./dist/bin/ffmpeg -formats 2>/dev/null | grep -E "mp4|mov|avi|mpegts"
```

All required codecs and formats must appear in the output. If any are missing, revisit the configure flags.

---

### Step 5 — Windows Minimal Build

For Windows, building from source requires MSYS2/MinGW or a CI environment. Use the following approach:

**5.1 — Use BtbN pre-built minimal releases as a base:**

Download from: `https://github.com/BtbN/FFmpeg-Builds/releases`  
Select: `ffmpeg-n6.1-latest-win64-gpl-shared-6.1.zip`

> This is still larger than ideal but far smaller than a random "full static" build. For production, set up a CI pipeline (GitHub Actions + MSYS2) that runs the same `./configure` from Step 4.2 targeting Windows.

**5.2 — Store the exact binary source in version control:**

Create `scripts/ffmpeg_sources.json`:
```json
{
  "linux_x64": {
    "build_script": "scripts/build_minimal_ffmpeg.sh",
    "expected_size_mb": 20
  },
  "windows_x64": {
    "source": "https://github.com/BtbN/FFmpeg-Builds/releases/...",
    "sha256": "FILL_IN_AFTER_DOWNLOAD",
    "expected_size_mb": 35
  },
  "macos_arm64": {
    "build_script": "scripts/build_minimal_ffmpeg.sh",
    "expected_size_mb": 18
  }
}
```

> 📌 **COMMIT C3 — After binaries are verified locally (Step 4.6 checks all pass)**
> Commit only the build script and source manifest — never the compiled binaries themselves. Confirm `.gitignore` excludes `scripts/dist/` before committing.
> ```bash
> git add scripts/build_minimal_ffmpeg.sh scripts/ffmpeg_sources.json .gitignore
> git commit -m "build: add minimal ffmpeg build script and verified dist binaries"
> ```

---

### Step 6 — Update PyInstaller / Packaging

**6.1 — Remove the old fat binaries from the spec file:**

In your `.spec` file, find and replace the `binaries` section:

```python
# BEFORE (remove this):
binaries=[
    ('bin/ffmpeg.exe', '.'),
    ('bin/ffprobe.exe', '.'),
]

# AFTER:
import os
_bundle_ffmpeg = os.environ.get("BUNDLE_FFMPEG", "1") == "1"
_bin_ext = ".exe" if sys.platform == "win32" else ""

binaries = []
if _bundle_ffmpeg:
    binaries = [
        (f'scripts/dist/bin/ffmpeg{_bin_ext}', '.'),
        (f'scripts/dist/bin/ffprobe{_bin_ext}', '.'),
    ]
```

Setting `BUNDLE_FFMPEG=0` before building produces a "no-bundle" distribution for server/power users.

**6.2 — Update `datas` if needed:**

Make sure `binary_resolver.py` is included in the bundle (it should be auto-detected as an import, but verify).

> 📌 **COMMIT C4 — After Step 7 dialog is implemented and manually tested**
> ```bash
> git add ClipSorter.spec main.py   # adjust filenames to match your project
> git commit -m "packaging: update spec and add missing-binary startup dialog"
> ```

---

### Step 7 — Missing Binary UX (Required for No-Bundle Mode)

In your main GUI entry point (e.g., `main.py` or `app.py`), add a startup dependency check:

```python
from binary_resolver import check_all_dependencies

def on_app_start():
    missing = check_all_dependencies()
    if missing:
        show_missing_ffmpeg_dialog(missing)
        return  # Do not proceed with app init
    # ... normal startup continues
```

The `show_missing_ffmpeg_dialog` function must:
1. Display a clear, non-technical message: *"ClipSorter needs FFmpeg to process videos. It wasn't found on your system."*
2. Provide a **"Download FFmpeg"** button that opens `https://ffmpeg.org/download.html` in the system browser.
3. Provide a **"Browse..."** button to let the user locate an existing `ffmpeg` binary manually. On confirmation, persist the path to app config and call `os.environ[FFMPEG_ENV_KEY] = chosen_path`.
4. On next launch, `binary_resolver` will pick up the persisted env/config path via Priority 1.

---

### Step 8 — Validation Checklist

Run every test before merging:

```
[ ] ls -lh dist/bin/ffmpeg dist/bin/ffprobe  →  both under 15 MB
[ ] ./dist/bin/ffmpeg -codecs shows: h264, hevc, libx264, aac
[ ] ./dist/bin/ffmpeg -formats shows: mp4, mov, avi, mpegts
[ ] Smoke test: H.264 MP4 input → no transcode path → output identical
[ ] HEVC transcode: H.265 MKV input → output is H.264 MP4
[ ] 4K downscale: 3840x2160 input → output is 1920x1080, aspect ratio correct
[ ] Short-file rejection: file under minimum duration → rejected early by qc_video.py
[ ] Missing binary: remove ffmpeg from PATH and bundle → app shows dialog, does not crash
[ ] Build size: du -sh ClipSorter.app or ClipSorter-setup.exe → confirm reduction from baseline
```

> 📌 **COMMIT C5 — Only after every checkbox above is ticked**
> Do not mark Phase A done until all tests pass. Do not skip failing tests and commit anyway.
> ```bash
> git commit -m "chore: Phase A validation complete — all smoke tests passing"
> ```
>
> **Then open a PR into `main`.** The PR description must include:
> - Before size: `~450 MB`
> - After size: actual measured output from `du -sh`
> - Link to the CI run or local test log showing all 9 checks green
>
> **Do not begin Phase B until this PR is merged.**

---

## PHASE B — PyAV Full Integration (Next Major Iteration)

> Begin this phase only after Phase A is stable and **merged into `main`**. This is the true HandBrake-level architecture.

> **Create a new branch before writing any Phase B code:**
> ```bash
> git checkout main
> git pull
> git checkout -b feature/pyav-integration
> ```
> Phase B must never be mixed into the Phase A branch or commits.

---

### Step 9 — Replace `ffprobe` Subprocess Calls with PyAV

Install PyAV (initially using its bundled FFmpeg — you will replace this in Step 11):
```bash
pip install av
```

**9.1 — Replace `_video_codec_name` in `converter.py`:**

```python
# BEFORE
def _video_codec_name(filepath: str) -> str:
    cmd = [resolve_binary("ffprobe"), "-v", "quiet",
           "-select_streams", "v:0", "-show_entries",
           "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
           filepath]
    return subprocess.check_output(cmd).decode().strip()

# AFTER
import av

def _video_codec_name(filepath: str) -> str:
    with av.open(filepath) as container:
        if not container.streams.video:
            return ""
        return container.streams.video[0].codec_context.name
```

**9.2 — Replace `_video_resolution` in `converter.py`:**

```python
# BEFORE (subprocess ffprobe)

# AFTER
def _video_resolution(filepath: str) -> tuple[int, int]:
    with av.open(filepath) as container:
        stream = container.streams.video[0]
        return stream.width, stream.height
```

**9.3 — Replace `_run_ffprobe_duration_seconds` in `qc_video.py`:**

```python
# AFTER
import av

def _run_ffprobe_duration_seconds(filepath: str) -> float:
    with av.open(filepath) as container:
        if container.duration is None:
            return 0.0
        return float(container.duration) / av.time_base
```

---

### Step 10 — Replace `ffmpeg` Subprocess Calls with PyAV Transcoding

This is the most involved step. Replace the transcoding pipeline in `converter.py`.

**10.1 — Normalization + 1080p rescale + HEVC-to-H264 transcode:**

```python
import av

def transcode_to_canonical(input_path: str, output_path: str) -> None:
    """
    Converts any input to 1080p H.264/AAC MP4.
    Equivalent to the ffmpeg -vf scale=-2:1080 -c:v libx264 -pix_fmt yuv420p -c:a aac pipeline.
    """
    with av.open(input_path) as in_container:
        in_video = in_container.streams.video[0]
        in_audio = in_container.streams.audio[0] if in_container.streams.audio else None

        # Calculate output dimensions (aspect-ratio preserving, height=1080, width multiple of 2)
        src_w, src_h = in_video.width, in_video.height
        target_h = 1080
        target_w = int(src_w * target_h / src_h)
        if target_w % 2 != 0:
            target_w += 1

        with av.open(output_path, "w", format="mp4") as out_container:
            out_video = out_container.add_stream("libx264", rate=in_video.average_rate)
            out_video.width = target_w
            out_video.height = target_h
            out_video.pix_fmt = "yuv420p"
            out_video.options = {"preset": "medium", "crf": "23"}

            out_audio = None
            if in_audio:
                out_audio = out_container.add_stream("aac")
                out_audio.sample_rate = in_audio.sample_rate
                out_audio.layout = in_audio.layout

            for packet in in_container.demux(in_video, *([in_audio] if in_audio else [])):
                if packet.stream == in_video:
                    for frame in packet.decode():
                        # Rescale frame if needed
                        if frame.width != target_w or frame.height != target_h:
                            frame = frame.reformat(
                                width=target_w, height=target_h, format="yuv420p"
                            )
                        out_packet = out_video.encode(frame)
                        if out_packet:
                            out_container.mux(out_packet)
                elif in_audio and packet.stream == in_audio:
                    for frame in packet.decode():
                        out_packet = out_audio.encode(frame)
                        if out_packet:
                            out_container.mux(out_packet)

            # Flush encoders
            for pkt in out_video.encode():
                out_container.mux(pkt)
            if out_audio:
                for pkt in out_audio.encode():
                    out_container.mux(pkt)
```

> 📌 **COMMIT C6 — After all subprocess calls are replaced and regression tests pass**
> Run the same smoke tests from Step 8 against the PyAV code paths before committing.
> ```bash
> git add src/converter.py src/qc_video.py
> git commit -m "refactor: replace ffmpeg/ffprobe subprocess calls with PyAV"
> ```

---

### Step 11 — Build a Custom PyAV Wheel (Eliminate PyAV's Bundled Full FFmpeg)

PyAV ships with a full-fat FFmpeg. To get to true HandBrake weight, compile it against your minimal build.

```bash
# Clone PyAV
git clone https://github.com/PyAV-Org/PyAV.git pyav_src
cd pyav_src

# Point PyAV to your already-built minimal FFmpeg from Step 4
# Set PKG_CONFIG_PATH to your minimal ffmpeg dist
export PKG_CONFIG_PATH="$(pwd)/../ffmpeg_src/dist/lib/pkgconfig"
export LDFLAGS="-L$(pwd)/../ffmpeg_src/dist/lib"
export CFLAGS="-I$(pwd)/../ffmpeg_src/dist/include"

# Build PyAV against it
pip install Cython
python setup.py build_ext --inplace

# Result: av/ directory using only your minimal FFmpeg libs
```

Package the resulting `av/` extension files into your PyInstaller bundle. The binary deps become just the `.so`/`.pyd` PyAV extension files backed by your minimal static libs — no separate executables needed.

> 📌 **COMMIT C7 — After PyAV wheel is built, packaged, and full pipeline verified**
> ```bash
> git add pyav_src/ ClipSorter.spec
> git commit -m "build: link PyAV against minimal custom FFmpeg, eliminate bundled full build"
> ```
> Then open a PR into `main` with before/after size numbers and full regression test results.

---

## Summary of Outcomes

| Phase | Approach | Bundle Size | Effort | Risk |
|-------|----------|-------------|--------|------|
| Baseline | Full-fat static ffmpeg+ffprobe | ~450 MB | — | — |
| **Phase A** | **Custom minimal binaries** | **~15–25 MB** | Medium | Low — subprocess architecture unchanged |
| **Phase B** | **PyAV with custom FFmpeg** | **~5–15 MB** | High — refactor all media calls | Medium — behavior must be regression-tested |
| Phase A no-bundle | System FFmpeg only | ~0 MB multimedia | Low | Users must have FFmpeg installed |

---

## Files Created / Modified by This Plan

```
CREATED:
  src/binary_resolver.py              ← new: smart binary resolution
  scripts/build_minimal_ffmpeg.sh     ← new: minimal FFmpeg build script
  scripts/ffmpeg_sources.json         ← new: pinned binary source manifest

MODIFIED:
  src/converter.py                    ← replace hardcoded "ffmpeg"/"ffprobe" strings
  src/qc_video.py                     ← replace hardcoded "ffprobe" strings
  ClipSorter.spec (or build.py)       ← replace fat binary paths, add BUNDLE_FFMPEG flag
  main.py (or app.py)                 ← add startup dependency check + missing binary dialog

PHASE B ADDITIONS:
  src/converter.py                    ← replace subprocess transcode with PyAV
  src/qc_video.py                     ← replace subprocess probe with PyAV
  pyav_src/                           ← custom PyAV build pointing to minimal FFmpeg
```