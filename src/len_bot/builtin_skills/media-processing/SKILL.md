---
name: media-processing
description: Convert, trim, combine, or inspect audio, video, and image media using the task image's actual FFmpeg capabilities.
---

# Media processing

Use `ffmpeg` for concrete media transformations. Check the source streams and installed encoders and filters first (`ffmpeg -i`, and `ffprobe` if present), and build the command from what is installed.

- Decide which source streams to keep, their time range, target format, dimensions, frame rate, and audio treatment from the request. Keep the source file and write to a distinct output path under `/workspace/out`.
- Run the chosen command with explicit maps and codec settings. Check its exit status and output, then inspect duration, dimensions, audio channels, and representative frames or short playback segments to confirm the result contains the requested cut.
- For subtitles or text overlays, the image includes Noto CJK fonts; verify actual font selection and readable placement on sample frames. If a required encoder or filter is missing, report which one.
- Register the checked output via `deliver_file(path, name, note)`.
