Random Pixel Image, GIF & H.264 Video Generator — Windows Build

Features
--------
- About menu is positioned at the far-right side of the application menu bar and displays: Pixel Generator V1.1
- The About window includes a clickable GitHub project link that opens https://github.com/KastriotH/pixel-generator in the default web browser
- Default image size: 1920 × 1080
- Default color depth: 1 bit (pure black and pure white)
- Color depth selector offers exactly six choices: 1, 2, 4, 8, 16 and 24 bits; choosing a depth automatically generates a new image at that depth
- 1, 2, 4 and 8-bit images use random RGB palettes; 1-bit mode is exactly black and white
- 16-bit and 24-bit images use direct RGB color with the selected number of bits distributed across red, green and blue
- 24-bit mode is full RGB888 color with up to 16,777,216 possible colors
- Custom X/Y resolution, image preview and PNG export
- Width (X), height (Y) and a wide 750-pixel pixel-doubling slider share the top control row; the bilinear switch is moved to the right side of the row beneath
- Color depth selector, Generate Random Image, Generate Random Fractal, Save PNG and Export H.264 Video buttons share one horizontal row; the Bilinear smoothing switch sits immediately to their right
- Generate Random Fractal button creates a fresh Mandelbrot composition on every click
- Each fractal generation randomizes the view center, zoom level and color-cycle mapping; some generations show a full-set overview while others explore detailed boundary regions
- Fractals honor the selected 1–24-bit color depth and use the current pixel-block and bilinear preview settings
- Changing color depth while viewing a fractal generates a new randomized Mandelbrot view at the new depth
- Fast NumPy-based random pixel generation
- Pixel doubling slider: square pixel blocks from 1×1 to 32×32 for still images and video
- Moving the pixel doubling slider updates the image preview immediately; no regeneration button is needed
- Interactive Bilinear smoothing switch toggles between sharp pixel blocks and smooth bilinear interpolation; no secondary mode caption is shown beside the switch
- Bilinear mode updates the preview immediately and is also used for PNG and H.264 video output
- Bilinear interpolation blends neighboring colors and can introduce intermediate shades beyond the selected source color depth
- The application remembers the main window position between launches
- Window position is saved automatically after moving the window and when closing the application, in the current user profile
- Exact output dimensions are preserved; partial blocks are clipped at non-divisible edges
- H.264 MP4 video export (a fresh random pattern is generated for every output frame)
- Animated GIF export button is positioned immediately after Export H.264 Video and before Bilinear smoothing
- GIF export has fixed 384 × 216 resolution, exactly 5 seconds, and 150 frames at a 30 FPS average; it is independent of the main image resolution and H.264 duration/FPS controls
- GIF frames use the current color depth, pixel-doubling and bilinear settings, with a fresh random pattern for each frame
- GIF output uses a shared 256-color palette across frames for stable playback; GIF itself is limited to 256 colors per frame
- GIF timing uses 30 ms and 40 ms frame delays (GIF stores centisecond delays), distributed across 150 frames to total exactly 5,000 ms
- Video duration: 1–60 seconds
- Frame rate: 30, 60, or 120 FPS; the compact slider has exactly three positions
- Video duration slider has exactly 60 discrete whole-second positions (1–60 seconds), with a 600-pixel track for easier selection; it sits beside the compact three-position frame-rate slider (30, 60 or 120 FPS)
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

The build installs NumPy, Pillow, imageio-ffmpeg and PyInstaller. Pillow provides GIF encoding; no additional GIF library is required.
Window position settings are stored separately in the user profile (under %APPDATA%\RandomPixelGenerator on Windows); they do not need to be packaged with the EXE.
This package was prepared in a non-Windows environment. A native Windows
EXE has not been compiled or tested here.

Bitrate note
------------
200 Mbit/s is the requested H.264 target/max bitrate. The actual achieved
bitrate may be lower depending on resolution and visual content. High
target bitrates can create large MP4 files.
