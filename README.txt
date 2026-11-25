Random Pixel Image & H.264 Video Generator — Windows Build

Features
--------
- Default image size: 1920 × 1080
- Default color depth: 1 bit (pure black and pure white)
- Still images: 1–8 bit random palettes, custom X/Y resolution, preview and PNG export
- Fast NumPy-based pixel generation
- Pixel doubling slider: square pixel blocks from 1×1 to 8×8 for still images and video
- Exact output dimensions are preserved; partial blocks are clipped at non-divisible edges
- H.264 MP4 video export
- Video duration: 1–60 seconds
- Frame rate: 30, 60, or 120 FPS
- Video timescale: 0.25x–1.00x in 0.05x increments
- Fixed H.264 target bitrate: 200 Mbit/s (200,000 kbit/s)
- No bitrate slider; every video export uses the fixed 200 Mbit/s target
- FFmpeg child console windows are suppressed on Windows
- Video export streams frames to FFmpeg to limit memory use
- Video resolution limit: 8,294,400 pixels per frame (up to 3840 × 2160)

Windows executable build
------------------------
1. Install Python 3 for Windows from https://www.python.org/downloads/windows/
   and enable "Add Python to PATH".
2. Extract this ZIP archive.
3. Double-click build_windows.bat.
4. EXE will be created at:
   dist\RandomPixelGenerator.exe

The build installs NumPy, Pillow, imageio-ffmpeg and PyInstaller.
This package was prepared in a non-Windows environment. A native Windows
EXE has not been compiled or tested here.

Bitrate note
------------
200 Mbit/s is the requested H.264 target/max bitrate. The actual achieved
bitrate may be lower depending on resolution and visual content. High
target bitrates can create large MP4 files.
