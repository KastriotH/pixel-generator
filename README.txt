Random Pixel Image, GIF & H.264 Video Generator — Windows Build

Features
--------
- Themes menu includes all 30 curated ttkbootstrap themes: 15 families with Light and Dark variants (Bootstrap, PyData, Nord, Solarized, Catppuccin, Gruvbox, Dracula, Tokyo Night, One, Everforest, Vapor, Minty, Pulse, United and Sandstone)
- Theme changes apply immediately without restarting the application; Nord Dark is the default
- Selected theme is remembered between launches in a separate per-user theme_preference.json settings file
- Themed ttk controls, menus, classic Tk sliders, preview canvas and About hyperlink follow the active palette
- Themes menu is positioned immediately to the left of About at the far-right side of the application menu bar; About remains the rightmost menu and displays: Pixel Generator V1.1
- The About window includes a clickable GitHub project link that opens https://github.com/KastriotH/pixel-generator in the default web browser
- Default image size: 1920 × 1080
- Default color depth: 1 bit (pure black and pure white)
- Color depth selector offers exactly six choices: 1, 2, 4, 8, 16 and 24 bits; choosing a depth automatically generates a new image at that depth
- 1, 2, 4 and 8-bit images use random RGB palettes; 1-bit mode is exactly black and white
- 16-bit and 24-bit images use direct RGB color with the selected number of bits distributed across red, green and blue
- 24-bit mode is full RGB888 color with up to 16,777,216 possible colors
- Resolution dropdown replaces the separate X/Y fields and offers 53 practical presets grouped as 4:3, 16:9 and 21:9-class ultrawide
- Default image resolution: 1920 × 1080 (16:9)
- Selecting a resolution immediately resizes the main application window to fit the selected image dimensions and regenerates the current random image or fractal at that resolution
- The application automatically detects the current screen dimensions on each resize; on Windows it uses the desktop work area (excluding the taskbar) where available, and keeps the complete window inside those boundaries
- When an image resolution is larger than the screen, only the application window and preview are constrained to fit; the selected full image resolution is preserved for PNG and other image output
- Saved window coordinates are revalidated against the currently detected screen work area at startup, so a window saved on a previous/larger display is brought back on-screen
- The preset list includes common sizes from compact resolutions through 8K-class output; mathematically possible resolutions are unlimited, so the dropdown uses a curated set of practical presets. Common ultrawide monitor modes are included in the 21:9 class even where panel timings are slightly wider or narrower than an exact 7:3 ratio
- Image preview and PNG export use the selected resolution
- The resolution dropdown and a wide 750-pixel pixel-doubling slider share the top control row
- Generate Random Image, Generate Random Fractal, Save PNG, Export H.264 Video and Export GIF controls appear first on the lower control row, followed by the color-depth selector and the Bilinear filtering switch
- Generate Random Fractal button creates a fresh Mandelbrot composition on every click
- Each fractal generation randomizes the view center, zoom level and color-cycle mapping; some generations show a full-set overview while others explore detailed boundary regions
- Fractals honor the selected 1–24-bit color depth and use the current pixel-block and bilinear preview settings
- Changing color depth while viewing a fractal generates a new randomized Mandelbrot view at the new depth
- Fast NumPy-based random pixel generation
- Pixel doubling slider: square pixel blocks from 1×1 to 32×32 for still images and video
- Moving the pixel doubling slider updates the image preview immediately; no regeneration button is needed
- Interactive Bilinear filtering switch toggles between sharp pixel blocks and smooth bilinear interpolation; no secondary mode caption is shown beside the switch
- Bilinear mode updates the preview immediately and is also used for PNG and H.264 video output
- Bilinear interpolation blends neighboring colors and can introduce intermediate shades beyond the selected source color depth
- The application remembers the main window position between launches
- Window position is saved automatically after moving the window and when closing the application, in the current user profile
- Exact output dimensions are preserved; partial blocks are clipped at non-divisible edges
- H.264 MP4 video export (a fresh random pattern is generated for every output frame)
- Animated GIF export button follows Export H.264 Video; the color-depth selector is placed immediately before the Bilinear filtering switch
- GIF export offers 13 selectable preset resolutions: 32 × 24, 64 × 48, 96 × 64, 128 × 96, 160 × 128, 256 × 192, 320 × 200, 192 × 108, 384 × 216, 400 × 300, 512 × 384, 640 × 360 and 640 × 480; the default remains 384 × 216
- GIF duration slider provides 30 whole-second positions (1–30 seconds), defaults to 5 seconds and sits alongside the video duration and frame-rate controls; the selected GIF duration determines the total frame count (30 frames per second)
- GIF resolution is selected independently from the 13-item preset dropdown; the chosen width and height are applied to every generated frame and verified in the saved GIF
- GIF frames use the current color depth, pixel-doubling and bilinear settings, with a fresh random pattern for each frame
- GIF output uses a shared 256-color palette across frames for stable playback; GIF itself is limited to 256 colors per frame
- GIF timing uses 30 ms and 40 ms frame delays (GIF stores centisecond delays), distributed across the selected frame count to total the exact selected whole-second duration
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
1. Install Python 3.10 or newer for Windows from https://www.python.org/downloads/windows/
   and enable "Add Python to PATH".
2. Extract this ZIP archive.
3. Double-click build_windows.bat.
4. EXE will be created at:
   dist\RandomPixelGenerator.exe

The build installs NumPy, Pillow, imageio-ffmpeg, ttkbootstrap 2.2.7 and PyInstaller. ttkbootstrap supplies the 30 built-in themes; Pillow provides GIF encoding, so no additional GIF library is required. GIF palette generation uses a small sample sheet and regenerates frames from per-frame seeds to keep memory use controlled for longer exports.
Window position settings are stored separately in the user profile (under %APPDATA%\RandomPixelGenerator on Windows); they do not need to be packaged with the EXE. The selected theme is saved separately in theme_preference.json in the same folder.
This package was prepared in a non-Windows environment. A native Windows
EXE has not been compiled or tested here.

Bitrate note
------------
200 Mbit/s is the requested H.264 target/max bitrate. The actual achieved
bitrate may be lower depending on resolution and visual content. High
target bitrates can create large MP4 files.

GIF frame handling
------------------
GIF export preserves every requested frame, including consecutive identical
frames that can occur with very small output resolutions or large pixel blocks.
This keeps the selected 30 FPS frame count and exact total duration consistent
across all supported GIF resolution presets.

Theme startup compatibility
---------------------------
The ttkbootstrap Style engine is initialized with Style(theme=...), not
Style(master=...). ttkbootstrap 2.2.7 binds its process-wide Style singleton to
the existing Tk root window; passing master= is unsupported and causes startup
to fail. The GUI smoke test uses a strict Style stub to catch that regression.

