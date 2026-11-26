# Pixel-Generator v1.3
Random Pixel Image, Fractal, GIF & H.264 Video Generator — Windows Build

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
- Generate Random Fractal button uses an adjacent Fractal type dropdown with seven families: Mandelbrot, Julia Set, Burning Ship, Tricorn (Mandelbar), Multibrot (Power 3), Celtic Mandelbrot and Phoenix; Mandelbrot remains the default
- Each fractal generation randomizes the view center, zoom level and color-cycle mapping; Julia and Phoenix also randomize their defining complex parameters; some generations show broader overviews while others explore detailed regions
- Fractals honor the selected 1–24-bit color depth and use the current pixel-block and bilinear preview settings
- Changing the fractal type while viewing a fractal regenerates immediately; changing color depth or resolution preserves and re-renders the current fractal viewport
- Interactive fractal exploration: scroll the mouse wheel over the preview to zoom toward the pointer, click-drag to pan, and use Reset View to return to the randomized starting viewport; the preview shifts during dragging and re-renders on release
- Interactive navigation preserves Julia/Phoenix parameters and the current palette; it uses the selected Automatic, CPU or OpenCL GPU renderer and works with all seven fractal families
- Fractal renderer offers three modes: Automatic (benchmarks CPU vs OpenCL GPU), CPU (Numba multi-threaded), and GPU (OpenCL); the selected mode is remembered between launches
- Automatic mode benchmarks the selected fractal family at a representative resolution, caches the CPU/GPU decision by device/driver, CPU configuration, fractal family and selected output resolution, and prefers CPU when results are within 3%
- GPU mode uses PyOpenCL and the NVIDIA OpenCL driver; Automatic mode falls back to Numba CPU if no compatible OpenCL GPU is found or GPU initialization fails
- OpenCL GPU kernels use double precision for the fractal escape-time iteration; GPU computation is row-chunked to bound temporary memory and the existing color/palette pipeline is shared with CPU output
- Fractal families use escape-time equations: Mandelbrot (z²+c), Julia Set (z²+c with a randomized complex constant), Burning Ship (absolute real/imaginary components before squaring), Tricorn/Mandelbar (conjugate iteration), cubic Multibrot (z³+c), Celtic Mandelbrot (absolute real component of z²) and Phoenix (quadratic recurrence with a prior-iteration term)
- All fractal families support the same six color depths, pixel-doubling preview and bilinear filtering controls, and PNG export
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


You must have python installed if you want to compile it to exe with included .bat file.

<img width="1954" height="1270" alt="image" src="https://github.com/user-attachments/assets/27565c6c-e0ba-4434-a8a6-cf359f225200" />

<img width="1952" height="1260" alt="{5863C5D5-CCF0-4130-BC6D-EC47AABF5501}" src="https://github.com/user-attachments/assets/e5b82fc7-ccab-40bf-9be4-48190894ca7a" />
