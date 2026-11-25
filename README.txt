Random Pixel Image & H.264 Video Generator — Windows Build

Features
--------
- About menu is positioned at the far-right side of the application menu bar and displays: Pixel Generator V1.1
- The About window includes a clickable GitHub project link that opens https://github.com/KastriotH/pixel-generator in the default web browser
- Default image size: 1920 × 1080
- Default color depth: 1 bit (pure black and pure white)
- Color depth selector: 1–24 bits; choosing a depth automatically generates a new image at that depth
- 1–8 bit images use random RGB palettes; 1-bit mode is exactly black and white
- 9–24 bit images use direct RGB color with the selected number of bits distributed across red, green and blue
- 24-bit mode is full RGB888 color with up to 16,777,216 possible colors
- Custom X/Y resolution, image preview and PNG export
- Generate Random Fractal button creates a fresh Mandelbrot composition on every click
- Each fractal generation randomizes the view center, zoom level and color-cycle mapping; some generations show a full-set overview while others explore detailed boundary regions
- Fractals honor the selected 1–24-bit color depth and use the current pixel-block and bilinear preview settings
- Changing color depth while viewing a fractal generates a new randomized Mandelbrot view at the new depth
- Fast NumPy-based random pixel generation
- Pixel doubling slider: square pixel blocks from 1×1 to 32×32 for still images and video
- Moving the pixel doubling slider updates the image preview immediately; no regeneration button is needed
- Interactive bilinear smoothing switch toggles between crisp nearest-neighbor pixel blocks and bilinear interpolation
- Bilinear mode updates the preview immediately and is also used for PNG and H.264 video output
- Bilinear interpolation blends neighboring colors and can introduce intermediate shades beyond the selected source color depth
- The application remembers the main window position between launches
- Window position is saved automatically after moving the window and when closing the application, in the current user profile
- Exact output dimensions are preserved; partial blocks are clipped at non-divisible edges
- H.264 MP4 video export (random-pattern video generation)
- Video duration: 1–60 seconds
- Frame rate: 30, 60, or 120 FPS
- Video timescale: 0.25x–1.00x in 0.05x increments
- Fixed H.264 target bitrate: 200 Mbit/s (200,000 kbit/s)
- No bitrate slider; every video export uses the fixed 200 Mbit/s target
- FFmpeg child console windows are suppressed on Windows
- Video export streams frames to FFmpeg to limit memory use
- Video resolution limit: 8,294,400 pixels per frame (up to 3840 × 2160)

Memory note
-----------
24-bit images use three bytes per pixel for RGB color data. Large image dimensions
therefore require more memory than indexed 1–8 bit images.

Windows executable build
------------------------
1. Install Python 3 for Windows from https://www.python.org/downloads/windows/
   and enable "Add Python to PATH".
2. Extract this ZIP archive.
3. Double-click build_windows.bat.
4. EXE will be created at:
   dist\RandomPixelGenerator.exe

The build installs NumPy, Pillow, imageio-ffmpeg and PyInstaller.
Window position settings are stored separately in the user profile (under %APPDATA%\RandomPixelGenerator on Windows); they do not need to be packaged with the EXE.
This package was prepared in a non-Windows environment. A native Windows
EXE has not been compiled or tested here.

Bitrate note
------------
200 Mbit/s is the requested H.264 target/max bitrate. The actual achieved
bitrate may be lower depending on resolution and visual content. High
target bitrates can create large MP4 files.
