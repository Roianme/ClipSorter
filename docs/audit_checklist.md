| File | Function | Binary | Flags Used | Input Formats (Implicit) | Output Format (Implicit) | Notes |
|:-----|:---------|:-------|:-----------|:-------------------------|:-------------------------|:------|
| src/converter.py | `_video_codec_name` | ffprobe | `-show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1` | Any | — | Extracts codec name |
| src/converter.py | `_video_resolution` | ffprobe | `-show_entries stream=width,height -of csv=s=x:p=0` | Any | — | Extracts video resolution |
| src/qc_video.py | `_run_ffprobe_duration_seconds` | ffprobe | `-show_entries format=duration -of default=noprint_wrappers=1:nokey=1` | Any | — | Extracts media duration |
| src/converter.py | `_convert_video` (copy path) | ffmpeg | `-c copy` | H.264 (MP4/MOV) | MP4 | Copy stream if already H.264 & 1080p |
| src/converter.py | `_convert_video` (transcode path) | ffmpeg | `-c:v libx264 -crf (config) -preset faster -pix_fmt yuv420p -c:a aac -b:a 128k -map 0:v:0 -map 0:a?` | Any (incl. HEVC) | MP4 | Main video transcoding logic |
| src/converter.py | `_convert_video` (rescale path) | ffmpeg | `-vf scale=-2:1080` (added to transcode) | 4K+ | MP4 | Rescales video to 1080p |
| src/converter.py | `_convert_audio` | ffmpeg | `-codec:a libmp3lame -b:a (config)` | Any audio | MP3 | Audio conversion to MP3 |
| tests/test_converter.py | `require_ffmpeg` | ffmpeg, ffprobe | `-version` | — | — | Checks binary availability |
| tests/test_duplicate.py | `require_ffmpeg` | ffmpeg, ffprobe | *No direct flags, but used to create dummy files or verify availability* | — | — | Checks binary availability |
| tests/test_qc_audio.py | *(setup/teardown)* | ffmpeg, ffprobe | `-version` | — | — | Checks binary availability |
| tests/test_qc_video.py | `_make_mp4_with_ffmpeg` | ffmpeg | `-f lavfi -i color=c=black:s=1920x1080:d={duration} -vf format=yuv420p` | `lavfi` (color gen) | MP4 | Creates dummy MP4 for testing |
| tests/test_qc_video.py | *(setup/teardown)* | ffmpeg, ffprobe | `-version` | — | — | Checks binary availability |

---

### Step 1.3 — Derived Minimum Component List

```
DECODERS:    h264, hevc, aac, mp3, pcm_s16le, pcm_s24le
ENCODERS:    libx264, aac, libmp3lame
DEMUXERS:    mov,mp4,m4a,3gp,3g2,mj2, matroska,webm, avi, mpegts, mpeg, wav
MUXERS:      mp4
PARSERS:     h264, hevc, aac, mpegaudio
FILTERS:     scale, format
PROTOCOLS:   file, pipe
BSF:         h264_mp4toannexb, hevc_mp4toannexb
```

**Reasoning for additions/modifications:**
*   `ENCODERS`: Added `libmp3lame` based on `src/converter.py`'s `_convert_audio` function.
*   `PROTOCOLS`: Added `pipe` because `subprocess.Popen` is used with `stdout=subprocess.PIPE` for progress parsing in `_run_ffmpeg_with_progress`.
*   `DEMUXERS`: The `ffmpeg -f lavfi` command in `_make_mp4_with_ffmpeg` implies `lavfi` protocol, but `lavfi` is an input *device*, not a demuxer or protocol relevant for FFmpeg compilation flags in this context. The core demuxers are derived from supported video/audio containers.

---

I have completed the exhaustive codebase audit and derived the minimum component list. I am now awaiting confirmation before proceeding to the next step.
