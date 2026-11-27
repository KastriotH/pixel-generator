Random Pixel Image, Fractal, GIF & OpenCL-Accelerated H.264 / H.265 Video Generator — Windows Build

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
- Generate Random Image, Generate Random Fractal, Save PNG, Export Video and Export GIF controls appear first on the lower control row, followed by the color-depth selector and the Bilinear filtering switch
- Generate Random Fractal button uses an adjacent Fractal type dropdown with seven families: Mandelbrot, Julia Set, Burning Ship, Tricorn (Mandelbar), Multibrot (Power 3), Celtic Mandelbrot and Phoenix; Mandelbrot remains the default
- Each fractal generation randomizes the view center, zoom level and color-cycle mapping; Julia and Phoenix also randomize their defining complex parameters; some generations show broader overviews while others explore detailed regions
- Fractals honor the selected 1–24-bit color depth and use the current pixel-block and bilinear preview settings
- Changing the fractal type while viewing a fractal regenerates immediately; changing color depth or resolution also regenerates the currently selected fractal family
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
- Bilinear mode updates the preview immediately and is also used for PNG and H.264/AVC or H.265/HEVC video output
- Bilinear interpolation blends neighboring colors and can introduce intermediate shades beyond the selected source color depth
- The application remembers the main window position between launches
- Window position is saved automatically after moving the window and when closing the application, in the current user profile
- Exact output dimensions are preserved; partial blocks are clipped at non-divisible edges
- H.264/AVC or H.265/HEVC MP4 export generates a fresh random pixel image on every frame when the current source is Generate Random Image; when the current source is a fractal, it rotates a snapshot of that fractal. Rotation is smooth from 0° to a selected 0–720° angle
- H.264/AVC and H.265/HEVC export use the Renderer dropdown: Automatic prefers the available OpenCL GPU and falls back to CPU, GPU forces OpenCL, and CPU keeps the NumPy/Pillow + FFmpeg filter pipeline
- OpenCL random-video rendering synthesizes fresh random pixel patterns and applies the progressive 0–720° rotation together in a single GPU kernel, then transfers small frame batches to FFmpeg for H.264/AVC or H.265/HEVC encoding
- OpenCL video batches are memory-bounded (approximately 32 MB per batch, maximum four frames) to keep 1080p and 4K exports within practical GPU memory use
- Fractal Animation Studio applies video rotation with OpenCL when the selected fractal renderer is GPU; CPU mode continues to use FFmpeg
- Fractal Animation Studio can also export an animated fractal GIF alongside MP4; it reuses the current fractal family, saved viewport and complex parameters, custom palette, zoom target, pixel size, bilinear setting and 0–720° rotation
- Fractal Animation Studio GIF export includes a dedicated resolution dropdown with exactly the same 13 presets as the normal GIF exporter; its selected resolution is applied to the actual fractal rendering and every saved GIF frame
- Fractal Animation Studio GIFs use the standard GIF timing: 30 FPS and 1–30 seconds, regardless of the MP4 frame-rate selector; a shared palette is sampled from the animation to keep colors stable
- Video codec selector offers H.264/AVC and H.265/HEVC. H.265/HEVC is the default to preserve the previous export behavior.
- Bitrate-controlled H.264/AVC and H.265/HEVC exports use a fixed 200 Mbit/s target. Fresh random-image video at 1×1 automatically switches to codec-specific Constant Quality Mode. H.264 NVENC uses VBR-CQ 12; H.265 NVENC uses VBR-CQ 20 with a 200 Mbit/s ceiling. The CPU H.264 fallback uses QP 12; the CPU H.265 fallback uses CRF 20 with a 200 Mbit/s VBV ceiling. Both codecs encode 1×1 frames as intra-only.
- H.264/AVC prefers NVIDIA h264_nvenc and falls back to CPU libx264 when NVENC is unavailable; H.265/HEVC prefers NVIDIA hevc_nvenc and falls back to CPU libx265. Each codec has an independent runtime encoder probe and fallback cache.
- OpenCL accelerates random-frame generation and image rotation; NVENC accelerates video compression when available. If NVENC cannot initialize, CPU software encoding remains available.
- Animated GIF export button follows Export Video; the color-depth selector is placed immediately before the Bilinear filtering switch
- GIF export offers 13 selectable preset resolutions: 32 × 24, 64 × 48, 96 × 64, 128 × 96, 160 × 128, 256 × 192, 320 × 200, 192 × 108, 384 × 216, 400 × 300, 512 × 384, 640 × 360 and 640 × 480; the default remains 384 × 216
- GIF duration slider provides 30 whole-second positions (1–30 seconds), defaults to 5 seconds and sits alongside the video duration and frame-rate controls; the selected GIF duration determines the total frame count (30 frames per second)
- GIF resolution is selected independently from the 13-item preset dropdown; the chosen width and height are applied to every generated frame and verified in the saved GIF
- GIF frames use the current color depth, pixel-doubling and bilinear settings, with a fresh random pattern for each frame
- GIF output uses a shared 256-color palette across frames for stable playback; GIF itself is limited to 256 colors per frame
- GIF timing uses 30 ms and 40 ms frame delays (GIF stores centisecond delays), distributed across the selected frame count to total the exact selected whole-second duration
- Video duration: 1–60 seconds
- Frame rate: 30, 60, or 120 FPS; the compact slider has exactly three positions
- Video duration slider has exactly 60 discrete whole-second positions (1–60 seconds), with a 600-pixel track for easier selection; it sits beside the compact three-position frame-rate slider (30, 60 or 120 FPS)
- Video image rotation has a 0–720° slider and Clockwise/Counterclockwise direction selector; 0° leaves the image unchanged, 360° completes one full turn and 720° completes two full turns, and rotation is smooth across the video. FFmpeg CPU-path direction mapping is validated using decoded video frames; OpenCL uses the matching image-coordinate convention
- H.264/AVC and H.265/HEVC use a fixed 200 Mbit/s target for normal exports; the target bitrate selector has been removed
- Fresh random-image video at 1×1 automatically uses Constant Quality Mode; other pixel sizes and fractal video remain at the fixed 200 Mbit/s target
- The codec is selectable in the main video controls and Fractal Animation Studio; H.265/HEVC remains the default
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

The build installs NumPy, Numba, llvmlite, PyOpenCL, Pillow, imageio-ffmpeg, ttkbootstrap 2.2.7 and PyInstaller. ttkbootstrap supplies the 30 built-in themes; PyOpenCL supplies the OpenCL Python bindings; Pillow provides GIF encoding, so no additional GIF library is required. GIF palette generation uses a small sample sheet and regenerates frames from per-frame seeds to keep memory use controlled for longer exports.
Window position settings are stored separately in the user profile (under %APPDATA%\RandomPixelGenerator on Windows); they do not need to be packaged with the EXE. The selected theme is saved separately in theme_preference.json in the same folder.
This package was prepared in a non-Windows environment. A native Windows
EXE has not been compiled or tested here.

Video rate-control note
------------------------
Normal H.264/AVC and H.265/HEVC exports use a fixed 200 Mbit/s target. Random
image video at pixel size 1×1 automatically switches to Constant Quality Mode
because independent full-resolution random pixels are difficult to compress
under a fixed bitrate without losing contrast and detail. H.264 NVENC uses
VBR-CQ 12 for stability on Windows. H.265 uses VBR-CQ 20 with a 200 Mbit/s
maximum, while the CPU libx265 fallback uses CRF 20 and a 200 Mbit/s VBV
ceiling. This prevents H.265 1×1 exports from reaching multi-gigabit rates and
reduces file size and playback load. H.264 Quality Mode remains uncapped.
Pixel sizes 2×2 through 32×32, fractal snapshots and Fractal Animation Studio
continue to use the 200 Mbit/s target. Actual bitrate in target mode can vary
with frame complexity and encoder rate control.

GIF frame handling
------------------
GIF export preserves every requested frame, including consecutive identical
frames that can occur with very small output resolutions or large pixel blocks.
This keeps the selected 30 FPS frame count and exact total duration consistent
across all supported GIF resolution presets. The Fractal Animation Studio GIF
export builds a shared palette from representative moments in the zoom journey,
then renders and quantizes each final frame at the selected GIF resolution.

Theme startup compatibility
---------------------------
The ttkbootstrap Style engine is initialized with Style(theme=...), not
Style(master=...). ttkbootstrap 2.2.7 binds its process-wide Style singleton to
the existing Tk root window; passing master= is unsupported and causes startup
to fail. The GUI smoke test uses a strict Style stub to catch that regression.



GPU acceleration requirements
-----------------------------
- Install a current NVIDIA GeForce driver for the RTX 3070 Ti. The Windows driver provides the vendor OpenCL implementation; PyOpenCL alone is not an OpenCL device driver.
- PyOpenCL's Windows wheel uses the Khronos OpenCL ICD Loader. The NVIDIA driver registers the actual NVIDIA OpenCL device with Windows.
- In the application, choose Automatic to benchmark the selected fractal on CPU and GPU, CPU to force the Numba renderer, or GPU to force OpenCL. The selected mode is remembered between launches. The same Renderer selection controls H.264 and H.265 video frame generation/rotation: Automatic tries OpenCL and falls back to CPU, GPU forces OpenCL, and CPU forces the CPU frame-generation/FFmpeg rotation path.
- Automatic mode caches a decision for each fractal family and exact selected image resolution, tied to the CPU, Numba version, GPU device, driver and PyOpenCL version.
- If no OpenCL GPU is available, Automatic mode uses the Numba CPU renderer for fractals and the CPU random-frame + FFmpeg rotation path for video exports. Explicit GPU mode displays a diagnostic instead of silently changing modes.
- GPU device compilation is performed by the installed driver on first use. The first GPU render may take extra time while its OpenCL program is compiled; subsequent renders reuse the program.
- GPU rendering uses FP64 to closely match the existing CPU fractal calculations. Small floating-point differences between CPU and GPU implementations can occur at a few escape-boundary pixels.
- To run a CPU/GPU comparison on the PC, run: `py -3 benchmark_cpu_gpu.py`. This script benchmarks all seven fractal families at 1920×1080 and 3840×2160 and writes CSV/JSON results.
- To check CPU/GPU image agreement on a PC with an OpenCL GPU, run: `py -3 test_opencl_fractal_backend.py`. The GPU-specific portion is skipped when no compatible OpenCL GPU is present.


OpenCL GPU validation
---------------------
1. Update/install the NVIDIA GeForce driver for the RTX 3070 Ti. PyOpenCL is a Python binding; the actual OpenCL implementation is supplied by the NVIDIA driver.
2. Rebuild the EXE with build_windows.bat. The build collects PyOpenCL's native extension, required DLLs, package data and metadata without recursively collecting unrelated test modules.
3. Run `py -3 diagnose_opencl.py` from the extracted source folder to list OpenCL platforms/devices and check FP64 support. The RTX 3070 Ti must appear as an OpenCL GPU with double-precision support.
4. Launch Pixel Generator and choose GPU to force the RTX 3070 Ti, CPU to force the CPU, or Automatic. For fractals, Automatic benchmarks and caches the CPU/GPU choice; for video exports, Automatic uses OpenCL when available and falls back to CPU. The export completion dialog identifies the renderer and video encoder actually used.
5. Run `py -3 test_opencl_fractal_backend.py` to compare CPU/GPU image output on a PC with a compatible OpenCL GPU. Run `py -3 benchmark_cpu_gpu.py` for fractal timings at 1920 × 1080 and 3840 × 2160.
6. Run `py -3 benchmark_video_backends.py` to compare CPU vs OpenCL random-frame generation and rotation at 1920 × 1080. Use `--width`, `--height`, `--seconds` and `--fps` to test other video modes.

GPU benchmark note
-----------------
The development environment used to prepare this package has no compatible OpenCL GPU, so it cannot report RTX 3070 Ti timings. The included CPU/GPU benchmark scripts measure your actual hardware; no GPU speedup is assumed or hard-coded. The first OpenCL render includes driver kernel compilation, so the first export may take longer while the video kernels are compiled and cached for subsequent exports.

Fractal Workspace features
--------------------------
The Fractal Tools menu adds five creative-workflow upgrades:

- Fractal bookmarks: save a named fractal view and restore its fractal family, complex parameters, exact center/zoom, image dimensions, color depth, pixel-block size, bilinear setting and custom palette. Manage bookmarks to load or delete them.
- Undo/Redo navigation: mouse-wheel zoom, click-and-drag panning, Reset View and palette changes are tracked in a 100-step history. Ctrl+Z and Ctrl+Y navigate backward and forward through the current fractal session.
- Fractal Gallery: new fractal generations are automatically saved as PNG plus JSON metadata by default. Automatic saving can be toggled from Fractal Tools. The gallery keeps the newest 250 entries; users can load, delete or open the gallery folder. Pan/zoom redraws are not automatically duplicated as new gallery entries.
- Custom color palettes: create named gradients with 2–16 hexadecimal color stops, add/edit/remove stops using the color picker, save and apply palettes, or return to the built-in Random spectrum. Custom gradients are applied in both Numba CPU and OpenCL GPU rendering paths and are retained in bookmarks, gallery metadata and batch outputs.
- Batch fractal generation: generate 100 or 1,000 images, selecting a specific fractal family or randomizing across all seven. Each output is a PNG with a matching JSON file containing the fractal coordinates, family, palette and render settings. Batch jobs show progress and can be cancelled; optional gallery auto-save follows the gallery preference.
- Fractal Animation Studio: render an H.264/AVC or H.265/HEVC MP4 zoom journey from the current fractal view toward a selected target point. Choose a 1–60 second duration, 30/60/120 FPS, zoom factor, target X/Y position, 0–720° rotation and rotation direction. The fractal zoom and rotation happen together. It uses the selected CPU/GPU/Automatic rendering mode and preserves the current fractal family, complex parameters and custom palette, along with selected pixel doubling and bilinear filtering. MP4 output is limited to 4K (8,294,400 pixels per frame).
- Fractal Animation Studio also has an Export GIF action. Select one of the same 13 GIF output resolutions as the main GIF exporter (32×24 through 640×480). The animated GIF follows the studio's current fractal zoom, target, rotation, pixel size, palette and renderer; GIF output is fixed at 30 FPS and supports 1–30 seconds. It uses a shared sampled palette and preserves the requested frame count, including duplicate frames.

Fractal Workspace data is stored under the per-user application directory:
%APPDATA%\RandomPixelGenerator\FractalWorkspace\
- bookmarks.json stores saved views.
- custom_palettes.json and active_palette.json store user gradients and the selected palette.
- Gallery\ contains auto-saved and manually retained PNG/JSON gallery entries.
- gallery_settings.json stores the gallery auto-save preference.

Workspace tools require no additional third-party dependencies beyond the application requirements. The animation studio and rotating-image export use the shared FFmpeg codec selection. The OpenCL video kernels are embedded in the Python source and are compiled by the installed graphics driver on first use. The regular Export Video button generates fresh random frames (using the selected color depth, pixel size and bilinear setting) when the current source is a random image. When the current source is a fractal, it rotates a snapshot of the current fractal preview. OpenCL performs random frame generation and rotation together when GPU or Automatic selects an available device; CPU mode uses FFmpeg's threaded rotation filter. FFmpeg encodes either H.264/AVC or H.265/HEVC. NVIDIA h264_nvenc/hevc_nvenc is preferred when its runtime probe succeeds, falling back to CPU libx264/libx265 when unavailable. Its rotate filter uses positive angles for visually clockwise rotation (opposite Pillow), and the regression suite checks decoded frame orientation for both directions.

Regression tests
----------------
From the extracted source folder, run:

    py -3 test_video_rotation.py
    py -3 test_hevc_encoder.py
    py -3 test_video_codec_bitrate.py
    py -3 test_random_video_quality_mode.py
    py -3 test_quality_mode_encoder_probe.py
    py -3 test_ffmpeg_broken_pipe_diagnostics.py
    py -3 test_opencl_video_export.py
    py -3 test_fractal_workspace_features.py
    py -3 test_fractal_exploration.py
    py -3 test_opencl_fractal_backend.py
    py -3 test_gpu_full_render_pipeline.py
    py -3 test_numba_thread_optimization.py
    py -3 test_theme_gui_smoke.py

The OpenCL-specific hardware checks are skipped when no compatible OpenCL device is present. The OpenCL video-export tests use a mock renderer to verify GPU dispatch, frame batching, and CPU fallback without requiring an OpenCL device. The GUI smoke test requires a working Windows desktop session (or another Tk display server).



NVENC probe correction (November 2026)
--------------------------------------
The hardware-encoder capability test now uses a 256 × 256 input frame instead of
64 × 64. Some NVENC HEVC implementations reject 64 × 64 as below the minimum
supported dimensions and return "Frame dimensions are less than the minimum
supported value". That message refers to the tiny capability-test frame, not the
user's selected 1920 × 1080 output. The corrected probe prevents this false CPU
fallback while preserving the CPU libx265 fallback for genuinely unavailable
NVENC hardware or drivers.

H.264 / H.265 video encoding
----------------------------
- The Video codec selector offers H.264/AVC and H.265/HEVC. H.265/HEVC remains the default to preserve the earlier application behavior.
- Normal target-bitrate exports use a fixed 200 Mbit/s target; the bitrate selector has been removed from both video dialogs.
- Random-image video at 1×1 uses Constant Quality Mode automatically; other random pixel sizes and fractal exports retain the 200 Mbit/s target.
- H.264 probes h264_nvenc and falls back to CPU libx264. H.265 probes hevc_nvenc and falls back to CPU libx265. The two encoder capability results are cached independently.
- NVENC is selected only after FFmpeg successfully encodes an eight-frame 256 × 256 quality-mode probe. H.264 NVENC quality mode uses VBR-CQ 12 (`-rc vbr -cq 12 -b:v 0`) to avoid a Windows H.264 constant-QP crash observed on some driver/FFmpeg combinations. H.265 NVENC quality mode uses VBR-CQ 20, intra-only GOP, no B-frames/AQ/lookahead, and a 200 Mbit/s target/maximum. CPU H.264 uses QP 12 all-intra; CPU H.265 uses CRF 20 all-intra with a 200 Mbit/s VBV ceiling.
- The app searches for a system FFmpeg on PATH first, then the imageio-ffmpeg bundled executable. This permits a system build with NVIDIA NVENC support to be used when the bundled FFmpeg does not contain it.
- NVENC hardware encoding is independent of OpenCL frame generation and rotation. OpenCL prepares the frames; NVENC performs H.264/H.265 compression. If NVENC fails its runtime probe, the matching libx264/libx265 CPU encoder is selected.
- Normal exports use the fixed 200 Mbit/s target. H.265 1×1 Quality Mode is capped at 200 Mbit/s to avoid multi-gigabit 120 FPS files that can be difficult for desktop players. H.264 1×1 VBR-CQ remains uncapped. Actual bitrates can vary with content and encoder rate control.
- If FFmpeg exits while frames are being streamed, the error dialog now includes the FFmpeg exit code and captured encoder diagnostic instead of only showing `[Errno 32] Broken pipe`.
- To obtain NVENC when the bundled imageio-ffmpeg build lacks it, install a current FFmpeg build with h264_nvenc and/or hevc_nvenc enabled and make sure its ffmpeg.exe is available on PATH. The app tests the requested codec before using it.


H.264 1x1 random-video consistency update
------------------------------------------
H.264 random-image exports in 1x1 Quality Mode now use intra-only encoding: each
source frame is encoded independently instead of using inter-frame prediction.
The NVENC VBR-CQ 12 path disables B-frames, lookahead, spatial AQ and temporal AQ
to avoid temporal/perceptual quantization changes on completely independent
random-noise frames. The libx264 CPU fallback uses QP 12, one I-frame per source
frame, no B-frames and AQ disabled. The H.265 Quality Mode path is unchanged.
This intentionally favors consistent frame appearance over compression
efficiency; all-intra random-noise videos can be larger than inter-frame video.
The NVENC hardware path must still be confirmed on a PC with a supported NVIDIA
driver because this development environment has no accessible NVENC device.


H.264 1x1 frame-consistency update
---------------------------------
H.264 1x1 random-image Quality Mode now encodes each frame independently
(intra-only). NVENC uses VBR-CQ 12 with GOP length 0 (intra-only), no B-frames,
no lookahead, and spatial/temporal adaptive quantization disabled. The reason is
that every 1x1 random frame is a new independent noise pattern: inter-frame
prediction and adaptive temporal decisions are not useful and can create visible
frame-to-frame changes in contrast or brightness. The libx264 CPU fallback uses
QP 12 with one I-frame per source frame, no B-frames and AQ disabled.

The H.264 NVENC Quality Mode probe encodes an eight-frame sample using the
exact production settings before choosing the hardware encoder. H.265 1×1
Quality Mode now uses all-intra VBR-CQ 20 with a 200 Mbit/s ceiling on NVENC,
and CRF 20 with matching VBV ceiling on the libx265 fallback. Both H.265
encoders disable B-frames and adaptive quantization. This replaces the previous
unbounded constant-QP 12 HEVC mode, which could create multi-gigabit 120 FPS
files. CPU integration tests decode a 120-frame H.265 1×1 export, verify that
every frame is an I-frame, and check luminance consistency. The development
environment does not provide an NVIDIA NVENC device, so the final hardware
path must still be confirmed on the target Windows PC.


H.265 1x1 size and playback update
----------------------------------
H.265/HEVC random-image exports at pixel size 1×1 now use intra-only encoding,
matching the H.264 frame-independence strategy. HEVC NVENC uses VBR-CQ 20 with
a 200 Mbit/s target/maximum, GOP length 0, B-frames disabled, lookahead disabled,
and spatial/temporal AQ disabled. The libx265 fallback uses CRF 20, one I-frame
per source frame, AQ/B-frames disabled, and an x265 VBV ceiling of 200 Mbit/s.
This replaces the previous unbounded constant-QP 12 HEVC path, which could
produce multi-gigabit 120 FPS files that are difficult for desktop players to
handle. H.264 1×1 settings and all other export modes are unchanged. The new
integration tests create a 120 FPS HEVC clip, verify every frame is an I-frame,
and check decoded luminance consistency. The actual hevc_nvenc hardware path
must be confirmed on a Windows machine with a working NVIDIA driver.


VIDEO EXPORT CANCELLATION
-------------------------
The main Export Video workflow and Fractal Animation Studio now include a
Cancel Export button while a video is being rendered/encoded. Cancelling stops
the active FFmpeg process, interrupts pending frame writes, releases process
handles, and removes the incomplete MP4. The normal export controls become
available again after cancellation completes. Closing the application during a
video export also requests cancellation.

The cancellation control covers random-image videos, rotating fractal
snapshots, Fractal Animation Studio MP4 zoom animations, and Fractal Animation
Studio GIF animations. It stops FFmpeg for video and interrupts frame rendering
for GIF, then removes the incomplete output file. It also works with CPU and
OpenCL fractal rendering. Standalone random-image GIF export and fractal batch
generation are unchanged.

Regression coverage: test_video_export_cancellation.py

Cancellation cleanup reliability update
---------------------------------------
Video cancellation now waits for FFmpeg to exit and close its process streams,
then retries deletion of the incomplete MP4 for up to 10 seconds. This handles
short-lived Windows file-sharing locks caused by process teardown, antivirus
scanning or thumbnail/indexing services. Read-only attributes are cleared
before deletion is attempted. The cancellation result now checks whether the
file is actually gone: if Windows continues to hold the file after all retries,
the application displays a warning with the exact path and reason instead of
incorrectly reporting that the MP4 was deleted. The same cleanup is used for
regular H.264/H.265 exports and Fractal Animation Studio exports.

Regression coverage includes transient Windows-style PermissionError locks,
persistent locks, real FFmpeg process termination and partial-MP4 removal.


Fractal Animation Studio GIF export update
------------------------------------------
Fractal Animation Studio now offers separate Export MP4 and Export GIF
actions. The GIF action has its own resolution dropdown populated from the
exact same GIF_RESOLUTION_OPTIONS list as the main Pixel Generator GIF
exporter: 32×24, 64×48, 96×64, 128×96, 160×128, 256×192, 320×200, 192×108,
384×216, 400×300, 512×384, 640×360 and 640×480. The selected size is used for
fractal rendering, not just post-export scaling.

GIF animation uses 30 FPS (GIF centisecond timing) and supports 1–30 seconds,
independent of the MP4 frame-rate selector. The animation follows the current
fractal family, viewport, zoom factor, target X/Y, complex parameters, palette,
pixel size, bilinear setting and rotation angle/direction. A representative
set of frames builds one shared 256-color palette for stable color mapping;
every requested frame is kept in the output, including duplicates.

The studio GIF export shares the existing Cancel Export control. Cancellation
interrupts frame generation and removes the incomplete GIF; normal video
cancellation still terminates FFmpeg and cleans up the partial MP4.

Regression coverage: test_fractal_animation_gif.py and
test_fractal_animation_gif_ui.py.
