import json
import os
import queue
import random
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import imageio_ffmpeg
import numpy as np
from PIL import GifImagePlugin, Image, ImageTk

try:
    import ttkbootstrap
except ImportError:  # GUI startup reports a clear message if themes are unavailable.
    ttkbootstrap = None


IMAGE_MAX_SIDE = 20000
IMAGE_MAX_PIXELS = 100_000_000
VIDEO_MAX_PIXELS = 8_294_400  # 3840 × 2160
VIDEO_FPS_OPTIONS = (30, 60, 120)
COLOR_DEPTH_OPTIONS = (1, 2, 4, 8, 16, 24)
VIDEO_DEFAULT_FPS = 60
VIDEO_DEFAULT_SECONDS = 10
VIDEO_MIN_SECONDS = 1
VIDEO_MAX_SECONDS = 60
VIDEO_DEFAULT_BITRATE_KBPS = 200000
GIF_WIDTH = 384
GIF_HEIGHT = 216
GIF_DEFAULT_RESOLUTION = (GIF_WIDTH, GIF_HEIGHT)
GIF_RESOLUTION_OPTIONS = (
    (32, 24),
    (64, 48),
    (96, 64),
    (128, 96),
    (160, 128),
    (256, 192),
    (320, 200),
    (192, 108),
    (384, 216),
    (400, 300),
    (512, 384),
    (640, 360),
    (640, 480),
)
GIF_MIN_SECONDS = 1
GIF_MAX_SECONDS = 30
GIF_DEFAULT_SECONDS = 5
GIF_FPS = 30
PROJECT_URL = "https://github.com/KastriotH/pixel-generator"

# ttkbootstrap 2.2.x provides 15 curated theme families in light/dark pairs.
# Keep the family catalog explicit so the menu always exposes exactly 30 themes.
THEME_FAMILIES = (
    ("Bootstrap", "bootstrap"),
    ("PyData", "pydata"),
    ("Nord", "nord"),
    ("Solarized", "solarized"),
    ("Catppuccin", "catppuccin"),
    ("Gruvbox", "gruvbox"),
    ("Dracula", "dracula"),
    ("Tokyo Night", "tokyo-night"),
    ("One", "one"),
    ("Everforest", "everforest"),
    ("Vapor", "vapor"),
    ("Minty", "minty"),
    ("Pulse", "pulse"),
    ("United", "united"),
    ("Sandstone", "sandstone"),
)
THEME_MODES = ("light", "dark")
BUILTIN_THEME_NAMES = tuple(
    f"{family}-{mode}"
    for _label, family in THEME_FAMILIES
    for mode in THEME_MODES
)
DEFAULT_THEME = "nord-dark"

# Practical preset list for common 4:3, 16:9 and 21:9-class ultrawide formats.
# Each entry is (menu label, width, height). A literal infinite list of all
# mathematically possible dimensions cannot fit in a dropdown, so this offers
# common display sizes plus several larger exact-ratio options.
IMAGE_RESOLUTION_PRESETS = (
    # 4:3
    ("4:3 — 320 × 240", 320, 240),
    ("4:3 — 400 × 300", 400, 300),
    ("4:3 — 480 × 360", 480, 360),
    ("4:3 — 640 × 480", 640, 480),
    ("4:3 — 800 × 600", 800, 600),
    ("4:3 — 1024 × 768", 1024, 768),
    ("4:3 — 1152 × 864", 1152, 864),
    ("4:3 — 1280 × 960", 1280, 960),
    ("4:3 — 1400 × 1050", 1400, 1050),
    ("4:3 — 1600 × 1200", 1600, 1200),
    ("4:3 — 1920 × 1440", 1920, 1440),
    ("4:3 — 2048 × 1536", 2048, 1536),
    ("4:3 — 2560 × 1920", 2560, 1920),
    ("4:3 — 3200 × 2400", 3200, 2400),
    ("4:3 — 3840 × 2880", 3840, 2880),
    ("4:3 — 4096 × 3072", 4096, 3072),
    # 16:9
    ("16:9 — 640 × 360", 640, 360),
    ("16:9 — 800 × 450", 800, 450),
    ("16:9 — 960 × 540", 960, 540),
    ("16:9 — 1280 × 720", 1280, 720),
    ("16:9 — 1600 × 900", 1600, 900),
    ("16:9 — 1920 × 1080", 1920, 1080),
    ("16:9 — 2048 × 1152", 2048, 1152),
    ("16:9 — 2560 × 1440", 2560, 1440),
    ("16:9 — 2880 × 1620", 2880, 1620),
    ("16:9 — 3200 × 1800", 3200, 1800),
    ("16:9 — 3840 × 2160", 3840, 2160),
    ("16:9 — 4096 × 2304", 4096, 2304),
    ("16:9 — 5120 × 2880", 5120, 2880),
    ("16:9 — 7680 × 4320", 7680, 4320),
    # 21:9 ultrawide class: common display resolutions plus exact 7:3 sizes.
    ("21:9 — 1920 × 800", 1920, 800),
    ("21:9 — 840 × 360", 840, 360),
    ("21:9 — 1050 × 450", 1050, 450),
    ("21:9 — 1260 × 540", 1260, 540),
    ("21:9 — 1400 × 600", 1400, 600),
    ("21:9 — 1680 × 720", 1680, 720),
    ("21:9 — 1890 × 810", 1890, 810),
    ("21:9 — 2100 × 900", 2100, 900),
    ("21:9 — 2240 × 960", 2240, 960),
    ("21:9 — 2520 × 1080", 2520, 1080),
    ("21:9 — 2560 × 1080", 2560, 1080),
    ("21:9 — 2800 × 1200", 2800, 1200),
    ("21:9 — 2940 × 1260", 2940, 1260),
    ("21:9 — 3360 × 1440", 3360, 1440),
    ("21:9 — 3440 × 1440", 3440, 1440),
    ("21:9 — 3780 × 1620", 3780, 1620),
    ("21:9 — 3840 × 1600", 3840, 1600),
    ("21:9 — 4200 × 1800", 4200, 1800),
    ("21:9 — 4480 × 1920", 4480, 1920),
    ("21:9 — 5040 × 2160", 5040, 2160),
    ("21:9 — 5120 × 2160", 5120, 2160),
    ("21:9 — 5600 × 2400", 5600, 2400),
    ("21:9 — 6720 × 2880", 6720, 2880),
)
IMAGE_RESOLUTION_LABELS = tuple(item[0] for item in IMAGE_RESOLUTION_PRESETS)
IMAGE_RESOLUTION_LOOKUP = {
    label: (width, height)
    for label, width, height in IMAGE_RESOLUTION_PRESETS
}
DEFAULT_IMAGE_RESOLUTION = (1920, 1080)
DEFAULT_IMAGE_RESOLUTION_LABEL = "16:9 — 1920 × 1080"


def normalize_image_resolution(value):
    """Resolve a dropdown label to a supported (width, height) preset."""
    if isinstance(value, str):
        try:
            return IMAGE_RESOLUTION_LOOKUP[value]
        except KeyError as exc:
            raise ValueError(f"Unsupported image resolution: {value!r}") from exc
    if isinstance(value, (tuple, list)) and len(value) == 2:
        width, height = value
        if (width, height) in IMAGE_RESOLUTION_LOOKUP.values():
            return int(width), int(height)
    raise ValueError(f"Unsupported image resolution: {value!r}")


def get_window_position_path():
    """Return a per-user location for the saved main-window coordinates."""
    if os.name == "nt":
        base_dir = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
    else:
        base_dir = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
    return os.path.join(base_dir, "RandomPixelGenerator", "window_position.json")


def load_window_position(path=None):
    """Load saved x/y coordinates, returning None for missing/invalid settings."""
    path = path or get_window_position_path()
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        x = settings.get("x")
        y = settings.get("y")
        if (
            isinstance(x, bool) or not isinstance(x, int)
            or isinstance(y, bool) or not isinstance(y, int)
        ):
            return None
        return x, y
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_window_position(x, y, path=None):
    """Persist x/y coordinates atomically so a partial write is not retained."""
    path = path or get_window_position_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as settings_file:
            json.dump({"x": int(x), "y": int(y)}, settings_file)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def get_theme_preference_path():
    """Return the per-user file used to remember the selected visual theme."""
    return os.path.join(
        os.path.dirname(get_window_position_path()), "theme_preference.json"
    )


def load_theme_preference(path=None):
    """Load a known built-in theme name, falling back safely to Nord Dark."""
    path = path or get_theme_preference_path()
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        theme_name = settings.get("theme")
        if isinstance(theme_name, str) and theme_name in BUILTIN_THEME_NAMES:
            return theme_name
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DEFAULT_THEME


def save_theme_preference(theme_name, path=None):
    """Persist a selected built-in theme without changing window-position data."""
    if theme_name not in BUILTIN_THEME_NAMES:
        raise ValueError(f"Unsupported application theme: {theme_name!r}")
    path = path or get_theme_preference_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as settings_file:
            json.dump({"theme": theme_name}, settings_file)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def detect_screen_work_area(root):
    """Detect the current display's usable work area in Tk coordinate units.

    Tk supplies the current screen dimensions on every supported platform.
    On Windows, SPI_GETWORKAREA additionally excludes the taskbar so the main
    window is not placed underneath it. The Win32 rectangle is scaled to Tk's
    coordinate units to account for per-process DPI scaling.
    """
    screen_width = max(1, int(root.winfo_screenwidth()))
    screen_height = max(1, int(root.winfo_screenheight()))

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            work_rect = RECT()
            user32 = ctypes.windll.user32
            # SPI_GETWORKAREA (0x0030) returns the primary monitor area without
            # taskbars and other reserved desktop bars.
            success = user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(work_rect), 0
            )
            if success:
                native_width = max(1, int(user32.GetSystemMetrics(0)))
                native_height = max(1, int(user32.GetSystemMetrics(1)))
                scale_x = screen_width / native_width
                scale_y = screen_height / native_height
                left = int(round(work_rect.left * scale_x))
                top = int(round(work_rect.top * scale_y))
                right = int(round(work_rect.right * scale_x))
                bottom = int(round(work_rect.bottom * scale_y))
                work_width = right - left
                work_height = bottom - top
                if work_width > 0 and work_height > 0:
                    return left, top, work_width, work_height
        except Exception:
            # Keep the application portable if Win32 metrics are unavailable.
            pass

    return 0, 0, screen_width, screen_height


def calculate_bounded_window_geometry(
    image_width,
    image_height,
    work_area,
    position=None,
    edge_margin=8,
    decoration_width=24,
    decoration_height=52,
):
    """Calculate window client size and position fully inside a screen work area.

    ``work_area`` is (left, top, width, height). Image dimensions are never
    modified; only the application window/preview is constrained to the
    detected display area. Decoration allowances account for title bar and
    window borders, while a small edge margin protects against rounding.
    """
    image_width = int(image_width)
    image_height = int(image_height)
    left, top, work_width, work_height = (int(value) for value in work_area)
    edge_margin = max(0, int(edge_margin))
    decoration_width = max(0, int(decoration_width))
    decoration_height = max(0, int(decoration_height))

    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive.")
    if work_width <= 0 or work_height <= 0:
        raise ValueError("Screen work-area dimensions must be positive.")

    available_width = max(
        1, work_width - (2 * edge_margin) - decoration_width
    )
    available_height = max(
        1, work_height - (2 * edge_margin) - decoration_height
    )

    requested_width = max(520, image_width + 32)
    requested_height = max(360, image_height + 150)
    window_width = min(requested_width, available_width)
    window_height = min(requested_height, available_height)

    if position is None:
        x = left + (work_width - window_width - decoration_width) // 2
        y = top + (work_height - window_height - decoration_height) // 2
    else:
        x, y = (int(value) for value in position)

    min_x = left + edge_margin
    min_y = top + edge_margin
    max_x = max(
        min_x,
        left + work_width - edge_margin - window_width - decoration_width,
    )
    max_y = max(
        min_y,
        top + work_height - edge_margin - window_height - decoration_height,
    )
    x = max(min_x, min(x, max_x))
    y = max(min_y, min(y, max_y))

    return window_width, window_height, x, y


def hidden_subprocess_options():
    """Return subprocess options that suppress child console windows on Windows."""
    if os.name != "nt":
        return {}

    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE

    return {
        "startupinfo": startup_info,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def make_random_palette(depth):
    """Create a random RGB palette for indexed color depths up to 8 bits."""
    if not 1 <= int(depth) <= 8:
        raise ValueError("Palette depth must be between 1 and 8 bits.")
    if int(depth) == 1:
        return [(0, 0, 0), (255, 255, 255)]
    return [
        (random.randrange(256), random.randrange(256), random.randrange(256))
        for _ in range(1 << int(depth))
    ]


def _depth_channel_bits(depth):
    """Distribute 9–24 RGB color bits as evenly as possible across R, G and B."""
    depth = int(depth)
    if not 9 <= depth <= 24:
        raise ValueError("Direct RGB depth must be between 9 and 24 bits.")
    base, remainder = divmod(depth, 3)
    return tuple(base + (1 if channel < remainder else 0) for channel in range(3))


def generate_rgb_pixels(width, height, depth, rng=None):
    """Generate random RGB pixels with exactly the selected available color bits."""
    if rng is None:
        rng = np.random.default_rng()
    channel_bits = _depth_channel_bits(depth)
    rgb = np.empty((height, width, 3), dtype=np.uint8)

    for channel, bits in enumerate(channel_bits):
        maximum = (1 << bits) - 1
        values = rng.integers(
            0, maximum + 1, size=(height, width), dtype=np.uint8
        )
        if maximum != 255:
            # Scale each channel's available levels across the full 0–255 range.
            values = (
                (values.astype(np.uint16) * 255 + maximum // 2) // maximum
            ).astype(np.uint8)
        rgb[:, :, channel] = values
    return rgb


def generate_pixelated_indices(width, height, color_count, pixel_size=1, rng=None):
    """Generate palette indices and expand each value into a square pixel block."""
    pixel_size = int(pixel_size)
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")

    if rng is None:
        rng = np.random.default_rng()

    grid_width = (width + pixel_size - 1) // pixel_size
    grid_height = (height + pixel_size - 1) // pixel_size
    indices = rng.integers(
        0, color_count, size=(grid_height, grid_width), dtype=np.uint8
    )
    if pixel_size > 1:
        indices = np.repeat(
            np.repeat(indices, pixel_size, axis=0), pixel_size, axis=1
        )[:height, :width]
    return indices


def scale_rgb_grid(rgb_grid, width, height, pixel_size=1, bilinear=False):
    """Scale an RGB sample grid to output dimensions using nearest or bilinear."""
    rgb_grid = np.asarray(rgb_grid, dtype=np.uint8)
    if rgb_grid.ndim != 3 or rgb_grid.shape[2] != 3:
        raise ValueError("RGB grid must have shape (height, width, 3).")

    if bilinear:
        # Bilinear interpolation blends neighboring sample colors. This can
        # introduce intermediate shades beyond the selected source color depth.
        scaled = Image.fromarray(np.ascontiguousarray(rgb_grid), mode="RGB").resize(
            (int(width), int(height)), Image.Resampling.BILINEAR
        )
        return np.asarray(scaled, dtype=np.uint8)

    pixel_size = int(pixel_size)
    expanded = np.repeat(
        np.repeat(rgb_grid, pixel_size, axis=0), pixel_size, axis=1
    )[:height, :width]
    return np.ascontiguousarray(expanded)


def generate_pixelated_rgb(width, height, depth, pixel_size=1, rng=None, bilinear=False):
    """Generate and expand a random RGB grid for 9–24-bit video frames."""
    pixel_size = int(pixel_size)
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    grid_width = (width + pixel_size - 1) // pixel_size
    grid_height = (height + pixel_size - 1) // pixel_size
    rgb_grid = generate_rgb_pixels(grid_width, grid_height, depth, rng=rng)
    return scale_rgb_grid(
        rgb_grid, width, height, pixel_size=pixel_size, bilinear=bilinear
    )


def generate_pixelated_frame(
    width, height, depth, pixel_size=1, rng=None, palette=None, bilinear=False
):
    """Generate one RGB video frame at the selected color depth and scale mode."""
    pixel_size = int(pixel_size)
    depth = int(depth)
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")
    if rng is None:
        rng = np.random.default_rng()

    grid_width = (int(width) + pixel_size - 1) // pixel_size
    grid_height = (int(height) + pixel_size - 1) // pixel_size
    if depth <= 8:
        if palette is None:
            palette = np.asarray(make_random_palette(depth), dtype=np.uint8)
        palette = np.asarray(palette, dtype=np.uint8)
        indices = rng.integers(
            0, len(palette), size=(grid_height, grid_width), dtype=np.uint8
        )
        rgb_grid = palette[indices]
    else:
        rgb_grid = generate_rgb_pixels(grid_width, grid_height, depth, rng=rng)

    return scale_rgb_grid(
        rgb_grid, width, height, pixel_size=pixel_size, bilinear=bilinear
    )


def _hsv_to_rgb_array(hue, saturation=0.92, value=1.0):
    """Convert HSV arrays to uint8 RGB without requiring an extra dependency."""
    hue = np.asarray(hue, dtype=np.float32) % 1.0
    h6 = hue * 6.0
    sector = np.floor(h6).astype(np.int8)
    fraction = h6 - np.floor(h6)
    p = value * (1.0 - saturation)
    q = value * (1.0 - saturation * fraction)
    t = value * (1.0 - saturation * (1.0 - fraction))

    red = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [value, q, p, p, t], default=value,
    )
    green = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [t, value, value, q, p], default=p,
    )
    blue = np.select(
        [sector == 0, sector == 1, sector == 2, sector == 3, sector == 4],
        [p, p, t, value, value], default=q,
    )
    rgb = np.stack((red, green, blue), axis=-1).clip(0.0, 1.0)
    return np.rint(rgb * 255.0).astype(np.uint8)


def generate_mandelbrot_image(
    width, height, depth, max_iterations=128, rows_per_chunk=48, rng=None
):
    """Generate a randomized, colorful Mandelbrot view at the selected depth.

    Every call chooses a different viewport (center and zoom) and color cycle,
    rather than rendering the same full-set composition every time. Pass a
    NumPy Generator in ``rng`` when deterministic output is useful for testing.

    The image is calculated in row chunks so large supported output dimensions
    do not require keeping the complete complex-number working set in memory.
    Depths 1–8 use an indexed palette; depths 9–24 use quantized direct RGB.
    """
    width = int(width)
    height = int(height)
    depth = int(depth)
    max_iterations = int(max_iterations)
    rows_per_chunk = int(rows_per_chunk)
    if width <= 0 or height <= 0:
        raise ValueError("Fractal width and height must be positive.")
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")
    if max_iterations < 8 or max_iterations > 2048:
        raise ValueError("Fractal iteration count must be between 8 and 2048.")
    if rows_per_chunk < 1:
        raise ValueError("Fractal row chunk size must be positive.")

    rng = np.random.default_rng() if rng is None else rng

    # Pick between the full set and detail-rich boundary locations. A random
    # zoom and a small center jitter make repeated clicks visibly different.
    boundary_centers = np.asarray(
        [
            (-0.75, 0.10),
            (-0.10, 0.65),
            (-1.25, 0.00),
            (-0.235125, 0.827215),
            (-0.745, 0.186),
            (-1.25066, 0.02012),
            (-0.101096, 0.956286),
            (-0.77468, 0.124),
            (-0.1592, 1.0317),
            (-1.768, 0.001),
            (0.285, 0.01),
            (-0.512, 0.521),
        ],
        dtype=np.float64,
    )
    if rng.random() < 0.16:
        # Occasionally show a differently framed overview of the whole set.
        center_real = -0.75 + float(rng.uniform(-0.10, 0.10))
        center_imag = float(rng.uniform(-0.10, 0.10))
        zoom = float(rng.uniform(0.85, 1.65))
    else:
        center_index = int(rng.integers(0, len(boundary_centers)))
        center_real, center_imag = boundary_centers[center_index]
        center_real += float(rng.normal(0.0, 0.018))
        center_imag += float(rng.normal(0.0, 0.018))
        zoom = float(10.0 ** rng.uniform(np.log10(1.5), np.log10(45.0)))

    # Keep the coordinate aspect ratio consistent with the output dimensions.
    horizontal_span = 3.5 / zoom
    vertical_span = horizontal_span * height / width
    x_coordinates = np.linspace(
        center_real - horizontal_span / 2.0,
        center_real + horizontal_span / 2.0,
        width,
        dtype=np.float64,
    )
    y_coordinates = np.linspace(
        center_imag - vertical_span / 2.0,
        center_imag + vertical_span / 2.0,
        height,
        dtype=np.float64,
    )

    # Randomize the color mapping independently of the selected viewport.
    palette_phase = float(rng.random())
    palette_cycles = float(rng.uniform(2.2, 5.8))

    indexed = depth <= 8
    color_count = 1 << depth
    if depth == 1:
        palette_rgb = np.asarray([(0, 0, 0), (255, 255, 255)], dtype=np.uint8)
    elif indexed:
        # Index zero is reserved for the interior; the remaining colors form
        # a random cyclic spectrum for points outside the Mandelbrot set.
        palette_t = np.linspace(0.0, 1.0, color_count - 1, dtype=np.float32)
        palette_hue = (palette_phase + palette_t * palette_cycles) % 1.0
        palette_rgb = np.zeros((color_count, 3), dtype=np.uint8)
        palette_rgb[1:] = _hsv_to_rgb_array(palette_hue)
    else:
        palette_rgb = None

    output = (
        np.empty((height, width), dtype=np.uint8)
        if indexed
        else np.empty((height, width, 3), dtype=np.uint8)
    )
    x_row = x_coordinates[np.newaxis, :]

    for row_start in range(0, height, rows_per_chunk):
        row_end = min(height, row_start + rows_per_chunk)
        chunk_height = row_end - row_start
        c_real = np.broadcast_to(x_row, (chunk_height, width))
        c_imag = y_coordinates[row_start:row_end, np.newaxis]

        z_real = np.zeros((chunk_height, width), dtype=np.float64)
        z_imag = np.zeros((chunk_height, width), dtype=np.float64)
        active = np.ones((chunk_height, width), dtype=bool)
        smooth_iterations = np.zeros((chunk_height, width), dtype=np.float32)

        active_indices = np.arange(chunk_height * width, dtype=np.int64)
        z_real_flat = z_real.ravel()
        z_imag_flat = z_imag.ravel()
        active_flat = active.ravel()
        smooth_flat = smooth_iterations.ravel()
        c_real_flat = np.broadcast_to(c_real, (chunk_height, width)).ravel()
        c_imag_flat = np.broadcast_to(c_imag, (chunk_height, width)).ravel()

        for iteration in range(max_iterations):
            if active_indices.size == 0:
                break
            zr = z_real_flat[active_indices]
            zi = z_imag_flat[active_indices]
            next_real = zr * zr - zi * zi + c_real_flat[active_indices]
            next_imag = 2.0 * zr * zi + c_imag_flat[active_indices]
            magnitude_squared = next_real * next_real + next_imag * next_imag
            z_real_flat[active_indices] = next_real
            z_imag_flat[active_indices] = next_imag

            escaped_local = magnitude_squared > 4.0
            if np.any(escaped_local):
                escaped_indices = active_indices[escaped_local]
                magnitude = np.sqrt(magnitude_squared[escaped_local])
                smooth_values = iteration + 1.0 - np.log2(np.log(magnitude))
                smooth_flat[escaped_indices] = np.clip(
                    smooth_values, 0.0, float(max_iterations)
                ).astype(np.float32)
                active_flat[escaped_indices] = False
                active_indices = active_indices[~escaped_local]

        escaped = ~active
        if depth == 1:
            # A true two-color rendering: interior black, escaped exterior white.
            chunk_output = escaped.astype(np.uint8)
        else:
            normalized = np.clip(
                smooth_iterations / float(max_iterations), 0.0, 1.0
            )
            if indexed:
                chunk_output = np.zeros((chunk_height, width), dtype=np.uint8)
                color_indices = 1 + np.minimum(
                    color_count - 2,
                    (normalized[escaped] * (color_count - 2)).astype(np.uint16),
                )
                chunk_output[escaped] = color_indices.astype(np.uint8)
            else:
                hue = (palette_phase + normalized * palette_cycles) % 1.0
                chunk_output = _hsv_to_rgb_array(hue)
                chunk_output[active] = (0, 0, 0)
                for channel, bits in enumerate(_depth_channel_bits(depth)):
                    levels = (1 << bits) - 1
                    quantized = np.rint(
                        chunk_output[:, :, channel].astype(np.float32) * levels / 255.0
                    )
                    chunk_output[:, :, channel] = np.rint(
                        quantized * 255.0 / levels
                    ).astype(np.uint8)

        output[row_start:row_end] = chunk_output

    if indexed:
        image = Image.frombytes("P", (width, height), output.tobytes())
        flat_palette = palette_rgb.reshape(-1).tolist()
        flat_palette.extend([0] * (768 - len(flat_palette)))
        image.putpalette(flat_palette)
        return image, color_count
    return Image.fromarray(output, mode="RGB"), color_count


def generate_random_image(width, height, depth):
    """Generate an indexed image (1–8 bits) or true-color RGB image (9–24 bits)."""
    depth = int(depth)
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")

    if depth <= 8:
        palette = make_random_palette(depth)
        indices = generate_pixelated_indices(width, height, len(palette), 1)
        flat_palette = [component for color in palette for component in color]
        flat_palette.extend([0] * (768 - len(flat_palette)))
        image = Image.frombytes("P", (width, height), indices.tobytes())
        image.putpalette(flat_palette)
        return image, len(palette)

    rgb = generate_rgb_pixels(width, height, depth)
    return Image.fromarray(rgb, mode="RGB"), 1 << depth


def pixelate_image(image, pixel_size=1, bilinear=False):
    """Apply square pixel blocks, optionally smoothing their transitions."""
    pixel_size = int(pixel_size)
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    if pixel_size == 1:
        return image

    width, height = image.size
    source_pixels = np.asarray(image)
    sampled = source_pixels[::pixel_size, ::pixel_size]

    if bilinear:
        if image.mode == "P":
            palette = image.getpalette()
            if palette is None:
                raise ValueError("Indexed source image is missing its color palette.")
            palette_rgb = np.asarray(palette[:768], dtype=np.uint8).reshape(-1, 3)
            sampled_rgb = palette_rgb[sampled]
        elif image.mode == "RGB":
            sampled_rgb = sampled
        else:
            sampled_rgb = np.asarray(image.convert("RGB"))[::pixel_size, ::pixel_size]
        scaled = Image.fromarray(
            np.ascontiguousarray(sampled_rgb.astype(np.uint8)), mode="RGB"
        ).resize((width, height), Image.Resampling.BILINEAR)
        return scaled

    expanded = np.repeat(
        np.repeat(sampled, pixel_size, axis=0), pixel_size, axis=1
    )[:height, :width]

    if image.mode == "P":
        result = Image.fromarray(expanded.astype(np.uint8), mode="P")
        palette = image.getpalette()
        if palette is not None:
            result.putpalette(palette)
        return result
    return Image.fromarray(expanded.astype(np.uint8), mode=image.mode)


def encode_random_h264_video(output_path, width, height, depth, duration_seconds=VIDEO_DEFAULT_SECONDS, fps=VIDEO_DEFAULT_FPS, bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS, pixel_size=1, progress_callback=None, bilinear=False):
    """Create an H.264 MP4 with a fresh random pattern on every output frame."""
    duration_seconds = int(duration_seconds)
    fps = int(fps)
    if not VIDEO_MIN_SECONDS <= duration_seconds <= VIDEO_MAX_SECONDS:
        raise ValueError("Video duration must be between 1 and 60 seconds.")
    if fps not in VIDEO_FPS_OPTIONS:
        raise ValueError("Frame rate must be 30, 60, or 120 fps.")
    bitrate_kbps = int(bitrate_kbps)
    if bitrate_kbps <= 0:
        raise ValueError("Video bitrate must be a positive value.")
    pixel_size = int(pixel_size)
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    depth = int(depth)
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")
    total_frames = fps * duration_seconds

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    # Confirm that the bundled FFmpeg build includes the requested H.264 encoder.
    encoder_check = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        **hidden_subprocess_options(),
    )
    if encoder_check.returncode != 0 or "libx264" not in encoder_check.stdout:
        raise RuntimeError(
            "The bundled FFmpeg does not provide the libx264 H.264 encoder."
        )

    palette = (
        np.asarray(make_random_palette(depth), dtype=np.uint8)
        if depth <= 8 else None
    )
    rng = np.random.default_rng()

    # yuv420p is broadly compatible with common video players.
    # The pad filter adds one black pixel on the right/bottom for odd dimensions.
    command = [
        ffmpeg_exe,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}",
        "-framerate", str(fps),
        "-i", "pipe:0",
        "-an",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-frames:v", str(total_frames),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-b:v", f"{bitrate_kbps}k",
        "-maxrate", f"{bitrate_kbps}k",
        "-bufsize", f"{bitrate_kbps * 2}k",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-movflags", "+faststart",
        output_path,
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
        **hidden_subprocess_options(),
    )

    try:
        # Generate one fresh random pattern for every output frame.
        # pattern for every output frame at the selected frame rate.
        for output_frame_number in range(1, total_frames + 1):
            frame_bytes = generate_pixelated_frame(
                width,
                height,
                depth,
                pixel_size=pixel_size,
                rng=rng,
                palette=palette,
                bilinear=bilinear,
            ).tobytes()
            process.stdin.write(frame_bytes)

            if progress_callback and (
                output_frame_number % 5 == 0
                or output_frame_number == total_frames
            ):
                progress_callback(output_frame_number)

        process.stdin.close()
        error_text = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(
                "FFmpeg failed to encode the video."
                + (f"\n\nFFmpeg details:\n{error_text}" if error_text else "")
            )

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("FFmpeg finished, but no MP4 file was created.")

    except Exception:
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass
        raise



def format_gif_resolution(resolution):
    """Format a GIF resolution tuple for the selector and status text."""
    width, height = normalize_gif_resolution(resolution)
    return f"{width}×{height}"


def normalize_gif_resolution(resolution):
    """Validate and return one of the 13 supported GIF resolution presets."""
    try:
        if isinstance(resolution, str):
            parts = resolution.lower().replace("×", "x").split("x")
            if len(parts) != 2:
                raise ValueError
            width, height = (int(part.strip()) for part in parts)
        else:
            width, height = (int(value) for value in resolution)
    except (TypeError, ValueError):
        raise ValueError("Select one of the supported GIF resolutions.") from None

    selected = (width, height)
    if selected not in GIF_RESOLUTION_OPTIONS:
        available = ", ".join(
            f"{w}×{h}" for w, h in GIF_RESOLUTION_OPTIONS
        )
        raise ValueError(f"Unsupported GIF resolution. Choose one of: {available}.")
    return selected


def gif_frame_durations_ms(frame_count, total_duration_ms):
    """Return centisecond-compatible delays totaling the requested duration.

    GIF stores frame delays in 10 ms units. At 30 FPS, 30 ms and 40 ms delays
    can be distributed so every whole-second duration is exact overall.
    """
    frame_count = int(frame_count)
    total_duration_ms = int(total_duration_ms)
    if frame_count <= 0 or total_duration_ms <= 0 or total_duration_ms % 10:
        raise ValueError(
            "GIF frame count and duration must be positive; duration must use 10 ms units."
        )

    total_centiseconds = total_duration_ms // 10
    base_ticks, extra_ticks = divmod(total_centiseconds, frame_count)
    if base_ticks < 1:
        raise ValueError("GIF frame delay must be at least 10 ms.")

    durations = []
    accumulator = 0
    for _ in range(frame_count):
        ticks = base_ticks
        accumulator += extra_ticks
        if accumulator >= frame_count:
            ticks += 1
            accumulator -= frame_count
        durations.append(ticks * 10)
    return durations


def _write_gif_frames_preserving_duplicates(output_path, frames, durations_ms):
    """Write every GIF frame, even when adjacent frames look identical.

    Pillow's high-level ``save_all`` writer coalesces consecutive identical
    frames by adding their delays together. That optimization is normally
    harmless, but tiny canvases and large pixel blocks can produce many
    repeated frames; our exporter validates a fixed 30-FPS frame count. Writing
    full-canvas frames directly through Pillow's GIF frame encoder preserves
    the requested frame count and keeps the rendered animation unchanged.

    All frames must be palette-indexed with the same global palette.
    """
    if not frames or len(frames) != len(durations_ms):
        raise ValueError("GIF frames and frame durations must have matching, non-zero lengths.")

    first = frames[0]
    if first.mode != "P":
        raise ValueError("GIF frames must use indexed-color (P) mode.")
    expected_size = first.size
    expected_palette = first.getpalette()
    if not expected_palette:
        raise ValueError("GIF frames must have a shared color palette.")

    for index, frame in enumerate(frames):
        if frame.mode != "P" or frame.size != expected_size:
            raise ValueError("All GIF frames must share the same indexed mode and dimensions.")
        if frame.getpalette() != expected_palette:
            raise ValueError("All GIF frames must use the same global color palette.")

    # Pillow's lower-level frame writer emits each full frame as a separate
    # image descriptor. Unlike Image.save(save_all=True), it does not merge
    # adjacent identical frames. A global palette keeps the GIF compact.
    global_info = {"loop": 0}
    with open(output_path, "wb") as gif_file:
        for header_block in GifImagePlugin._get_global_header(first, global_info):
            gif_file.write(header_block)

        for frame, duration_ms in zip(frames, durations_ms):
            GifImagePlugin._write_frame_data(
                gif_file,
                frame.copy(),
                (0, 0),
                {
                    "duration": int(duration_ms),
                    "disposal": 2,
                    "optimize": False,
                },
            )

        gif_file.write(b";")  # GIF trailer
        gif_file.flush()


def encode_random_gif(
    output_path,
    depth,
    pixel_size=1,
    duration_seconds=GIF_DEFAULT_SECONDS,
    progress_callback=None,
    bilinear=False,
    resolution=GIF_DEFAULT_RESOLUTION,
):
    """Export a 30-FPS random animated GIF at a preset size and selected duration."""
    depth = int(depth)
    pixel_size = int(pixel_size)
    duration_seconds = int(duration_seconds)
    gif_width, gif_height = normalize_gif_resolution(resolution)
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    if not GIF_MIN_SECONDS <= duration_seconds <= GIF_MAX_SECONDS:
        raise ValueError(
            f"GIF duration must be between {GIF_MIN_SECONDS} and {GIF_MAX_SECONDS} seconds."
        )

    total_frames = duration_seconds * GIF_FPS
    total_duration_ms = duration_seconds * 1000
    rng = np.random.default_rng()
    palette = (
        np.asarray(make_random_palette(depth), dtype=np.uint8)
        if depth <= 8 else None
    )
    # Keep memory predictable even at the 30-second / 900-frame maximum by
    # sampling small thumbnails for a shared palette, then regenerating frames
    # from their per-frame seeds for final encoding.
    sample_width = min(64, gif_width)
    sample_height = min(36, gif_height)
    frame_seeds = rng.integers(
        0, np.iinfo(np.uint64).max, size=total_frames, dtype=np.uint64
    )
    palette_samples = Image.new(
        "RGB", (sample_width, sample_height * total_frames)
    )

    for frame_index, seed in enumerate(frame_seeds):
        frame = generate_pixelated_frame(
            gif_width,
            gif_height,
            depth,
            pixel_size=pixel_size,
            rng=np.random.default_rng(int(seed)),
            palette=palette,
            bilinear=bilinear,
        )
        thumbnail = Image.fromarray(np.ascontiguousarray(frame), mode="RGB").resize(
            (sample_width, sample_height), Image.Resampling.BOX
        )
        palette_samples.paste(thumbnail, (0, frame_index * sample_height))

    try:
        shared_palette = palette_samples.quantize(
            colors=256,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        frames = []
        for frame_index, seed in enumerate(frame_seeds):
            frame = generate_pixelated_frame(
                gif_width,
                gif_height,
                depth,
                pixel_size=pixel_size,
                rng=np.random.default_rng(int(seed)),
                palette=palette,
                bilinear=bilinear,
            )
            rgb_frame = Image.fromarray(np.ascontiguousarray(frame), mode="RGB")
            indexed_frame = rgb_frame.quantize(
                palette=shared_palette,
                dither=Image.Dither.NONE,
            )
            frames.append(indexed_frame)
            if progress_callback:
                progress_callback(frame_index + 1)

        durations = gif_frame_durations_ms(total_frames, total_duration_ms)
        _write_gif_frames_preserving_duplicates(output_path, frames, durations)

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("GIF encoding finished, but no file was created.")

        with Image.open(output_path) as check:
            if check.size != (gif_width, gif_height):
                raise RuntimeError(
                    f"GIF encoder produced an unexpected resolution: {check.size}; "
                    f"expected {(gif_width, gif_height)}."
                )
            if getattr(check, "n_frames", 1) != total_frames:
                raise RuntimeError("GIF encoder produced an unexpected frame count.")
            actual_duration = 0
            for frame_index in range(check.n_frames):
                check.seek(frame_index)
                actual_duration += int(check.info.get("duration", 0))
            if actual_duration != total_duration_ms:
                raise RuntimeError(
                    f"GIF duration mismatch: expected {total_duration_ms} ms, "
                    f"got {actual_duration} ms."
                )
    except Exception:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass
        raise


class RandomPixelGenerator:
    """Random-pixel image, fractal, H.264 video and GIF generator."""

    def __init__(self, root):
        self.root = root
        self.root.title("Random Pixel Image & Video Generator")
        self.window_position_path = get_window_position_path()
        self.saved_window_position = load_window_position(self.window_position_path)
        self.theme_preference_path = get_theme_preference_path()
        self.current_theme = load_theme_preference(self.theme_preference_path)
        self.theme_var = tk.StringVar(value=self.current_theme)
        if ttkbootstrap is None:
            raise RuntimeError(
                "The theme engine is not installed. Run build_windows.bat or install "
                "ttkbootstrap 2.2.7 with: py -3 -m pip install ttkbootstrap==2.2.7"
            )
        # Attach ttkbootstrap's Style engine to the existing tkinter root.
        # This keeps the current Tkinter application structure and adds live themes.
        self.theme_style = ttkbootstrap.Style(theme=self.current_theme)
        self.theme_style.theme_use(self.current_theme)
        self._native_theme_menus = []
        self._window_geometry_initialized = False
        self._position_save_after_id = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Configure>", self._on_window_configure, add="+")
        self._create_menu()
        self.image = None
        self.base_image = None
        self.preview_photo = None
        self.current_depth = None
        self.current_color_count = None
        self.current_image_type = "random"

        self.result_queue = queue.Queue()
        self.video_queue = queue.Queue()
        self.gif_queue = queue.Queue()
        self.is_generating = False
        self.is_exporting_video = False
        self.is_exporting_gif = False

        self.width_var = tk.StringVar(value=str(DEFAULT_IMAGE_RESOLUTION[0]))
        self.height_var = tk.StringVar(value=str(DEFAULT_IMAGE_RESOLUTION[1]))
        self.resolution_var = tk.StringVar(value=DEFAULT_IMAGE_RESOLUTION_LABEL)
        self.depth_var = tk.StringVar(value="1")
        self.bilinear_var = tk.BooleanVar(value=False)
        self.pixel_size_var = tk.IntVar(value=1)
        self.pixel_size_label_var = tk.StringVar(value="1×1")
        self.fps_index_var = tk.IntVar(value=1)  # 0=30, 1=60, 2=120 FPS
        self.fps_label_var = tk.StringVar(value=f"{VIDEO_DEFAULT_FPS} FPS")
        self.duration_var = tk.IntVar(value=VIDEO_DEFAULT_SECONDS)
        self.duration_label_var = tk.StringVar(
            value=f"{VIDEO_DEFAULT_SECONDS} seconds"
        )
        self.gif_duration_var = tk.IntVar(value=GIF_DEFAULT_SECONDS)
        self.gif_resolution_var = tk.StringVar(
            value=format_gif_resolution(GIF_DEFAULT_RESOLUTION)
        )
        self.gif_duration_label_var = tk.StringVar(
            value=f"{GIF_DEFAULT_SECONDS} seconds"
        )
        self.current_gif_duration = GIF_DEFAULT_SECONDS
        self.current_gif_resolution = GIF_DEFAULT_RESOLUTION
        self.current_gif_frames = GIF_DEFAULT_SECONDS * GIF_FPS
        self.current_video_fps = VIDEO_DEFAULT_FPS
        self.current_video_frames = VIDEO_DEFAULT_FPS * VIDEO_DEFAULT_SECONDS
        self.current_video_duration = VIDEO_DEFAULT_SECONDS
        self.status_var = tk.StringVar(
            value="Ready — 1920 × 1080, 1-bit black and white."
        )

        # Resolution, pixel-size and interpolation controls share one row so
        # the image geometry and its rendering options stay together.
        settings_frame = ttk.Frame(root, padding=(12, 8, 12, 4))
        settings_frame.pack(fill="x")

        ttk.Label(settings_frame, text="Resolution:").grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        self.resolution_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.resolution_var,
            values=IMAGE_RESOLUTION_LABELS,
            width=24,
            state="readonly",
        )
        self.resolution_combo.grid(row=0, column=1, padx=(0, 14), sticky="w")
        self.resolution_combo.bind("<<ComboboxSelected>>", self._on_resolution_change)

        ttk.Label(settings_frame, text="Pixel doubling:").grid(
            row=0, column=2, padx=(0, 3), sticky="w"
        )
        self.pixel_size_scale = tk.Scale(
            settings_frame,
            variable=self.pixel_size_var,
            from_=1,
            to=32,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=750,
            command=self._on_pixel_size_change,
        )
        self.pixel_size_scale.grid(row=0, column=3, padx=(3, 4), sticky="w")
        ttk.Label(settings_frame, text="1×1").grid(
            row=0, column=4, padx=(0, 4), sticky="w"
        )
        ttk.Label(
            settings_frame, textvariable=self.pixel_size_label_var, width=5
        ).grid(row=0, column=5, padx=(0, 4), sticky="w")
        ttk.Label(settings_frame, text="32×32").grid(
            row=0, column=6, padx=(0, 12), sticky="w"
        )

        # Action buttons, color depth and bilinear filtering share this row.
        # Keep color depth directly before the bilinear filtering switch.
        depth_frame = ttk.Frame(settings_frame)
        depth_frame.grid(row=1, column=0, columnspan=11, sticky="ew", pady=(5, 0))
        self.generate_button = ttk.Button(
            depth_frame, text="Generate Random Image", command=self.generate_image
        )
        self.generate_button.pack(side="left", padx=(0, 6))

        self.fractal_button = ttk.Button(
            depth_frame, text="Generate Random Fractal", command=self.generate_fractal
        )
        self.fractal_button.pack(side="left", padx=6)

        self.save_button = ttk.Button(
            depth_frame, text="Save PNG...", command=self.save_image, state="disabled"
        )
        self.save_button.pack(side="left", padx=6)

        self.video_button = ttk.Button(
            depth_frame, text="Export H.264 Video...", command=self.export_video
        )
        self.video_button.pack(side="left", padx=6)

        self.gif_button = ttk.Button(
            depth_frame, text="Export GIF...", command=self.export_gif
        )
        self.gif_button.pack(side="left", padx=6)

        # Keep color depth immediately before the bilinear filtering option.
        ttk.Label(depth_frame, text="Color depth:").pack(side="left", padx=(14, 5))
        self.depth_combo = ttk.Combobox(
            depth_frame,
            textvariable=self.depth_var,
            values=[str(bit) for bit in COLOR_DEPTH_OPTIONS],
            width=5,
            state="readonly",
        )
        self.depth_combo.pack(side="left", padx=(0, 6))
        self.depth_combo.bind("<<ComboboxSelected>>", self._on_depth_change)
        ttk.Label(depth_frame, text="bits").pack(side="left", padx=(0, 8))

        self.bilinear_check = ttk.Checkbutton(
            depth_frame,
            text="Bilinear filtering",
            variable=self.bilinear_var,
            command=self._on_bilinear_change,
        )
        self.bilinear_check.pack(side="left", padx=(8, 0))

        # Keep duration and frame-rate controls close together. Both sliders
        # use identical track thickness and thumb dimensions so their tracks
        # line up vertically. The duration slider is half its former length.
        video_controls_frame = ttk.Frame(root, padding=(12, 0, 12, 6))
        video_controls_frame.pack(fill="x")

        duration_frame = ttk.Frame(video_controls_frame)
        duration_frame.grid(row=0, column=0, padx=(0, 10), sticky="nw")
        ttk.Label(duration_frame, text="Video duration:").grid(
            row=0, column=0, sticky="w"
        )
        self.duration_scale = tk.Scale(
            duration_frame,
            variable=self.duration_var,
            from_=VIDEO_MIN_SECONDS,
            to=VIDEO_MAX_SECONDS,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            # 60 discrete whole-second positions; at 600 px the thumb has
            # roughly 10 px per step, making each duration practical to select.
            length=600,
            width=15,
            sliderlength=18,
            highlightthickness=0,
            borderwidth=0,
            command=self._on_duration_change,
        )
        self.duration_scale.grid(row=1, column=0, sticky="w")
        ttk.Label(duration_frame, text="1 s").grid(row=2, column=0, sticky="w")
        ttk.Label(
            duration_frame, textvariable=self.duration_label_var
        ).grid(row=2, column=0)
        ttk.Label(duration_frame, text="60 s").grid(row=2, column=0, sticky="e")

        fps_frame = ttk.Frame(video_controls_frame)
        fps_frame.grid(row=0, column=1, padx=(0, 0), sticky="nw")
        ttk.Label(fps_frame, text="Video frame rate:").grid(
            row=0, column=0, sticky="w"
        )
        self.fps_scale = tk.Scale(
            fps_frame,
            variable=self.fps_index_var,
            from_=0,
            to=2,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=72,
            width=15,
            sliderlength=18,
            highlightthickness=0,
            borderwidth=0,
            command=self._on_fps_change,
        )
        self.fps_scale.grid(row=1, column=0, sticky="w")
        ttk.Label(fps_frame, textvariable=self.fps_label_var).grid(
            row=2, column=0, sticky="w"
        )

        gif_duration_frame = ttk.Frame(video_controls_frame)
        gif_duration_frame.grid(row=0, column=2, padx=(18, 0), sticky="nw")
        ttk.Label(gif_duration_frame, text="GIF duration:").grid(
            row=0, column=0, sticky="w"
        )
        self.gif_duration_scale = tk.Scale(
            gif_duration_frame,
            variable=self.gif_duration_var,
            from_=GIF_MIN_SECONDS,
            to=GIF_MAX_SECONDS,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=300,
            width=15,
            sliderlength=18,
            highlightthickness=0,
            borderwidth=0,
            command=self._on_gif_duration_change,
        )
        self.gif_duration_scale.grid(row=1, column=0, sticky="w")
        ttk.Label(gif_duration_frame, text="1 s").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Label(
            gif_duration_frame, textvariable=self.gif_duration_label_var
        ).grid(row=2, column=0)
        ttk.Label(gif_duration_frame, text="30 s").grid(
            row=2, column=0, sticky="e"
        )

        gif_resolution_frame = ttk.Frame(video_controls_frame)
        gif_resolution_frame.grid(row=0, column=3, padx=(18, 0), sticky="nw")
        ttk.Label(gif_resolution_frame, text="GIF resolution:").grid(
            row=0, column=0, sticky="w"
        )
        self.gif_resolution_combo = ttk.Combobox(
            gif_resolution_frame,
            textvariable=self.gif_resolution_var,
            values=[format_gif_resolution(size) for size in GIF_RESOLUTION_OPTIONS],
            width=10,
            state="readonly",
        )
        self.gif_resolution_combo.grid(row=1, column=0, sticky="w")

        self.progress = ttk.Progressbar(
            root, orient="horizontal", mode="determinate", maximum=self.current_video_frames
        )
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.progress.pack_forget()

        ttk.Label(root, textvariable=self.status_var, padding=(12, 0, 12, 8)).pack(
            anchor="w"
        )

        preview_frame = ttk.Frame(root, padding=8)
        preview_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            preview_frame, background="#282828", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_resize)

        # ttk widgets are themed by ttkbootstrap; apply matching colors to the
        # remaining classic Tk scales, canvas, menus and About hyperlink.
        self._apply_classic_widget_theme()

        self.root.update_idletasks()
        self.resize_window_to_image(*DEFAULT_IMAGE_RESOLUTION)
        self.generate_image()

        self.root.after(60, self._poll_image_result)
        self.root.after(80, self._poll_video_result)
        self.root.after(80, self._poll_gif_result)

    def _create_menu(self):
        """Create theme-family menus beside About at the right end of the menu bar."""
        self.menu_bar = ttk.Frame(self.root, padding=(8, 2, 12, 2))
        self.menu_bar.pack(fill="x")

        self.themes_menu = tk.Menu(self.root, tearoff=0)
        self._native_theme_menus = [self.themes_menu]
        for family_label, family_name in THEME_FAMILIES:
            family_menu = tk.Menu(self.themes_menu, tearoff=0)
            for mode in THEME_MODES:
                theme_name = f"{family_name}-{mode}"
                family_menu.add_radiobutton(
                    label=f"{family_label} {mode.title()}",
                    variable=self.theme_var,
                    value=theme_name,
                    command=lambda selected=theme_name: self.apply_theme(selected),
                )
            self.themes_menu.add_cascade(label=family_label, menu=family_menu)
            self._native_theme_menus.append(family_menu)

        self.themes_menu_button = ttk.Menubutton(
            self.menu_bar, text="Themes", menu=self.themes_menu
        )

        self.about_menu = tk.Menu(self.root, tearoff=0)
        self._native_theme_menus.append(self.about_menu)
        self.about_menu.add_command(
            label="Pixel Generator V1.1", command=self.show_about
        )
        self.about_menu_button = ttk.Menubutton(
            self.menu_bar, text="About", menu=self.about_menu
        )
        # Pack About first on the right so it remains the rightmost item;
        # Themes is then packed immediately to its left.
        self.about_menu_button.pack(side="right")
        self.themes_menu_button.pack(side="right", padx=(0, 8))
        self._apply_classic_widget_theme()

    def _apply_classic_widget_theme(self):
        """Bring non-ttk Tk widgets and native menus into the active palette."""
        if not hasattr(self, "theme_style"):
            return
        colors = self.theme_style.colors
        try:
            self.root.configure(background=colors.bg)
        except tk.TclError:
            pass

        for menu in getattr(self, "_native_theme_menus", ()):
            try:
                menu.configure(
                    background=colors.bg,
                    foreground=colors.fg,
                    activebackground=colors.selectbg,
                    activeforeground=colors.selectfg,
                    disabledforeground=colors.secondary,
                    selectcolor=colors.primary,
                    borderwidth=0,
                    relief="flat",
                )
            except tk.TclError:
                pass

        # Classic Tk Scale widgets are used for the long pixel/video/GIF sliders.
        for attribute_name in (
            "pixel_size_scale",
            "duration_scale",
            "fps_scale",
            "gif_duration_scale",
        ):
            scale = getattr(self, attribute_name, None)
            if scale is not None:
                try:
                    scale.configure(
                        background=colors.bg,
                        foreground=colors.fg,
                        troughcolor=colors.inputbg,
                        activebackground=colors.primary,
                        highlightbackground=colors.bg,
                        highlightcolor=colors.primary,
                        disabledforeground=colors.secondary,
                        borderwidth=0,
                        relief="flat",
                    )
                except tk.TclError:
                    pass

        canvas = getattr(self, "canvas", None)
        if canvas is not None:
            try:
                canvas.configure(
                    background=colors.bg,
                    highlightbackground=colors.border,
                    highlightcolor=colors.border,
                )
            except tk.TclError:
                pass

        project_link = getattr(self, "project_link", None)
        if project_link is not None:
            try:
                project_link.configure(
                    background=colors.bg,
                    foreground=colors.primary,
                    activebackground=colors.bg,
                    activeforeground=colors.info,
                )
            except tk.TclError:
                pass

    def apply_theme(self, theme_name=None):
        """Apply one of the 30 built-in ttkbootstrap themes and remember it."""
        theme_name = theme_name or self.theme_var.get()
        if theme_name not in BUILTIN_THEME_NAMES:
            messagebox.showerror(
                "Unknown theme", f"The theme {theme_name!r} is not available."
            )
            self.theme_var.set(self.current_theme)
            return False

        previous_theme = self.current_theme
        try:
            self.theme_style.theme_use(theme_name)
            self.current_theme = theme_name
            self.theme_var.set(theme_name)
            self._apply_classic_widget_theme()
            save_theme_preference(theme_name, self.theme_preference_path)
            return True
        except Exception as exc:
            # Roll back the radio-menu state if a theme cannot be applied.
            try:
                self.theme_style.theme_use(previous_theme)
            except Exception:
                pass
            self.current_theme = previous_theme
            self.theme_var.set(previous_theme)
            self._apply_classic_widget_theme()
            messagebox.showerror(
                "Theme change failed",
                f"Could not apply {theme_name}.\n\n{exc}",
            )
            return False

    def show_about(self):
        """Display the app version and a clickable link to its GitHub project."""
        dialog = tk.Toplevel(self.root)
        dialog.title("About")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        colors = self.theme_style.colors
        dialog.configure(background=colors.bg)

        content = ttk.Frame(dialog, padding=(20, 16))
        content.pack(fill="both", expand=True)

        ttk.Label(
            content,
            text="Pixel Generator V1.1",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="center", pady=(0, 10))

        ttk.Label(content, text="Project website:").pack(anchor="w")
        project_link = tk.Label(
            content,
            text=PROJECT_URL,
            fg=colors.primary,
            bg=colors.bg,
            activeforeground=colors.info,
            activebackground=colors.bg,
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
            takefocus=True,
        )
        project_link.pack(anchor="w", pady=(2, 14))
        self.project_link = project_link
        project_link.bind("<Button-1>", lambda _event: self.open_project_page())
        project_link.bind("<Return>", lambda _event: self.open_project_page())
        project_link.bind("<space>", lambda _event: self.open_project_page())

        ttk.Button(content, text="OK", command=dialog.destroy).pack(anchor="e")

        # Center the About window over the main application window.
        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        project_link.focus_set()

    @staticmethod
    def open_project_page():
        """Open the project's GitHub repository in the default browser."""
        try:
            opened = webbrowser.open_new_tab(PROJECT_URL)
        except Exception as exc:
            messagebox.showerror(
                "Unable to open link",
                f"Could not open the GitHub project page.\n\n{exc}",
            )
            return False
        if not opened:
            messagebox.showwarning(
                "Unable to open link",
                "Your default web browser could not be opened.",
            )
            return False
        return True

    def read_settings(self):
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            depth = int(self.depth_var.get())
            pixel_size = int(self.pixel_size_var.get())
            if not 1 <= depth <= 24:
                raise ValueError("Color depth must be between 1 and 24 bits.")
            if not 1 <= pixel_size <= 32:
                raise ValueError("Pixel size must be between 1x1 and 32x32.")
            if width <= 0 or height <= 0:
                raise ValueError("Width and height must be positive.")
            if (
                width > IMAGE_MAX_SIDE
                or height > IMAGE_MAX_SIDE
                or width * height > IMAGE_MAX_PIXELS
            ):
                raise ValueError(
                    "Maximum is 20,000 pixels per side and 100 million total pixels."
                )
            return width, height, depth, pixel_size
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return None

    def _on_resolution_change(self, _event=None):
        """Apply a resolution preset, resize the window, and regenerate the image."""
        if self.is_generating or self.is_exporting_video or self.is_exporting_gif:
            return
        try:
            width, height = normalize_image_resolution(self.resolution_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid resolution", str(exc))
            self.resolution_var.set(DEFAULT_IMAGE_RESOLUTION_LABEL)
            width, height = DEFAULT_IMAGE_RESOLUTION

        self.width_var.set(str(width))
        self.height_var.set(str(height))

        # _start_image_generation resizes the main window immediately before
        # launching the worker, and regenerates the current image/fractal type.
        if self.current_image_type == "fractal":
            self.generate_fractal()
        else:
            self.generate_image()

    def _on_depth_change(self, _event=None):
        """Regenerate immediately when the user selects a different color depth."""
        if self.is_generating or self.is_exporting_video or self.is_exporting_gif:
            return
        if self.current_image_type == "fractal":
            self.generate_fractal()
        else:
            self.generate_image()

    def _on_pixel_size_change(self, value=None):
        """Update the label and live preview as the pixel-size slider moves."""
        if value is not None:
            self.pixel_size_var.set(max(1, min(32, int(float(value)))))
        pixel_size = int(self.pixel_size_var.get())
        self.pixel_size_label_var.set(f"{pixel_size}×{pixel_size}")
        self._refresh_image_preview()

    def _on_bilinear_change(self):
        """Toggle bilinear rendering and refresh the preview immediately."""
        self._refresh_image_preview()

    def _refresh_image_preview(self):
        if self.base_image is not None and not self.is_generating:
            try:
                self.image = pixelate_image(
                    self.base_image,
                    int(self.pixel_size_var.get()),
                    bilinear=bool(self.bilinear_var.get()),
                )
                self.show_preview()
                self._update_image_status()
                self.save_button.configure(state="normal")
            except Exception as exc:
                self.status_var.set(f"Preview update failed: {exc}")

    def _update_image_status(self):
        if self.base_image is None or self.current_depth is None:
            return
        width, height = self.base_image.size
        pixel_size = int(self.pixel_size_var.get())
        render_mode = "Bilinear filtering" if self.bilinear_var.get() else "Sharp pixel blocks"
        source_label = "Mandelbrot fractal" if self.current_image_type == "fractal" else "Random image"
        label = (
            f"{source_label} | {width} × {height} | {self.current_depth}-bit source | "
            f"{self.current_color_count:,} source colors | "
            f"{pixel_size}×{pixel_size} blocks | {render_mode}"
        )
        if self.current_depth == 1:
            label += " (black/white source)"
        elif self.current_depth == 24:
            label += " (true color RGB)"
        self.status_var.set(label)

    def _get_selected_fps(self):
        index = max(0, min(2, int(self.fps_index_var.get())))
        return VIDEO_FPS_OPTIONS[index]

    def _on_fps_change(self, value=None):
        if value is not None:
            self.fps_index_var.set(max(0, min(2, int(float(value)))))
        self.fps_label_var.set(f"{self._get_selected_fps()} FPS")

    def _on_duration_change(self, _value=None):
        seconds = int(self.duration_var.get())
        self.duration_label_var.set(
            f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
        )

    def _on_gif_duration_change(self, _value=None):
        seconds = int(self.gif_duration_var.get())
        self.gif_duration_label_var.set(
            f"{seconds} second" if seconds == 1 else f"{seconds} seconds"
        )

    def resize_window_to_image(self, image_width, image_height):
        """Fit the app to the selected image while respecting detected screen bounds.

        The selected image's true output resolution is preserved. If it exceeds
        the desktop work area, only the main window and on-screen preview are
        constrained; PNG and video exports still use the full selected size.
        """
        self.root.update_idletasks()
        work_area = detect_screen_work_area(self.root)

        if not self._window_geometry_initialized:
            preferred_position = self.saved_window_position
        else:
            # When the image size changes, retain the current position if it
            # still fits on the detected display.
            preferred_position = (self.root.winfo_x(), self.root.winfo_y())

        window_width, window_height, x, y = calculate_bounded_window_geometry(
            image_width,
            image_height,
            work_area,
            position=preferred_position,
        )

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        # Never impose a minimum larger than the available work area. Allow
        # manual enlargement, but never beyond the detected desktop boundaries.
        max_client_width = max(1, work_area[2] - 16 - 24)
        max_client_height = max(1, work_area[3] - 16 - 52)
        self.root.minsize(min(520, window_width), min(360, window_height))
        self.root.maxsize(max_client_width, max_client_height)
        self.detected_screen_work_area = work_area
        self.detected_screen_resolution = (
            int(self.root.winfo_screenwidth()),
            int(self.root.winfo_screenheight()),
        )
        self._window_geometry_initialized = True

    def _on_window_configure(self, event):
        """Debounce position persistence while the user moves the window."""
        if event.widget is not self.root or not self._window_geometry_initialized:
            return
        if self._position_save_after_id is not None:
            try:
                self.root.after_cancel(self._position_save_after_id)
            except tk.TclError:
                pass
        self._position_save_after_id = self.root.after(350, self._save_window_position)

    def _save_window_position(self):
        self._position_save_after_id = None
        try:
            if self.root.state() != "normal":
                return
            x = int(self.root.winfo_x())
            y = int(self.root.winfo_y())
            # Ignore transient coordinates reported during minimize/restore.
            if x < -50000 or y < -50000:
                return
            save_window_position(x, y, self.window_position_path)
        except (OSError, tk.TclError, ValueError):
            # A read-only profile or a window closing during a move should not
            # prevent the application from closing normally.
            pass

    def on_close(self):
        """Save the final normal-state position and close the application."""
        if self._position_save_after_id is not None:
            try:
                self.root.after_cancel(self._position_save_after_id)
            except tk.TclError:
                pass
            self._position_save_after_id = None
        self._save_window_position()
        self.root.destroy()

    def generate_image(self):
        """Generate a random source image using the current controls."""
        self._start_image_generation("random")

    def generate_fractal(self):
        """Generate a new randomized Mandelbrot view using the current depth."""
        self._start_image_generation("fractal")

    def _start_image_generation(self, image_type):
        if self.is_generating or self.is_exporting_video or self.is_exporting_gif:
            return

        settings = self.read_settings()
        if settings is None:
            return
        width, height, depth, pixel_size = settings
        bilinear = bool(self.bilinear_var.get())

        self.is_generating = True
        self._set_action_buttons()
        self.progress.pack_forget()
        if image_type == "fractal":
            self.status_var.set(
                f"Generating randomized Mandelbrot fractal: {width} × {height}, "
                f"{depth}-bit, 128 iterations..."
            )
        else:
            self.status_var.set(
                f"Generating random image: {width} × {height}, {depth}-bit, "
                f"{pixel_size}×{pixel_size} pixel blocks, "
                f"{'bilinear filtering' if bilinear else 'sharp pixel blocks'}..."
            )
        self.resize_window_to_image(width, height)

        threading.Thread(
            target=self._image_worker,
            args=(width, height, depth, image_type),
            daemon=True,
        ).start()

    def _image_worker(self, width, height, depth, image_type="random"):
        try:
            if image_type == "fractal":
                image, color_count = generate_mandelbrot_image(width, height, depth)
            else:
                # Generate a full-detail source once. The slider derives each
                # live pixel-block preview from this same image, preserving its pattern.
                image, color_count = generate_random_image(width, height, depth)
            self.result_queue.put(
                ("success", image, width, height, depth, color_count, image_type)
            )
        except Exception as exc:
            self.result_queue.put(("error", str(exc)))

    def _poll_image_result(self):
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(60, self._poll_image_result)
            return

        self.is_generating = False
        self._set_action_buttons()

        if result[0] == "error":
            self.status_var.set("Image generation failed.")
            messagebox.showerror("Generation failed", result[1])
        else:
            _, self.base_image, width, height, depth, color_count, image_type = result
            self.current_depth = depth
            self.current_color_count = color_count
            self.current_image_type = image_type
            self._on_pixel_size_change()
            self.save_button.configure(state="normal")

        self.root.after(60, self._poll_image_result)

    def export_video(self):
        if self.is_generating or self.is_exporting_video or self.is_exporting_gif:
            return

        settings = self.read_settings()
        if settings is None:
            return
        width, height, depth, pixel_size = settings
        bilinear = bool(self.bilinear_var.get())

        if width * height > VIDEO_MAX_PIXELS:
            messagebox.showerror(
                "Video resolution too large",
                "H.264 video export is limited to 8,294,400 pixels per frame "
                "(up to 3840 × 2160 / 4K). Reduce the selected width or height.",
            )
            return

        duration_seconds = int(self.duration_var.get())
        fps = self._get_selected_fps()
        bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
        total_frames = fps * duration_seconds
        default_name = (
            f"random_pixels_{width}x{height}_{pixel_size}x{pixel_size}px_"
            f"{'bilinear' if bilinear else 'nearest'}_"
            f"{duration_seconds}s_{fps}fps_200mbit.mp4"
        )
        output_path = filedialog.asksaveasfilename(
            title="Export H.264 video",
            initialfile=default_name,
            defaultextension=".mp4",
            filetypes=[("MP4 video (H.264)", "*.mp4")],
        )
        if not output_path:
            return

        self.is_exporting_video = True
        self._set_action_buttons()
        self.current_video_fps = fps
        self.current_video_frames = total_frames
        self.current_video_duration = duration_seconds
        self.progress.configure(maximum=total_frames, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.status_var.set(
            f"Exporting H.264: {width} × {height}, {duration_seconds} seconds, "
            f"{fps} fps, {pixel_size}×{pixel_size} pixel blocks, "
            f"{'bilinear filtering' if bilinear else 'sharp pixel blocks'} mode, "
            f"new random pattern per frame, fixed 200 Mbit/s bitrate..."
        )

        threading.Thread(
            target=self._video_worker,
            args=(
                output_path, width, height, depth, duration_seconds,
                fps, bitrate_kbps, pixel_size, bilinear
            ),
            daemon=True,
        ).start()

    def export_gif(self):
        """Export a preset-resolution animated GIF at 30 FPS."""
        if self.is_generating or self.is_exporting_video or self.is_exporting_gif:
            return

        try:
            depth = int(self.depth_var.get())
            pixel_size = int(self.pixel_size_var.get())
            duration_seconds = int(self.gif_duration_var.get())
            gif_resolution = normalize_gif_resolution(self.gif_resolution_var.get())
            if depth not in COLOR_DEPTH_OPTIONS:
                raise ValueError("Select one of the available color depths: 1, 2, 4, 8, 16 or 24 bits.")
            if not 1 <= pixel_size <= 32:
                raise ValueError("Pixel size must be between 1x1 and 32x32.")
            if not GIF_MIN_SECONDS <= duration_seconds <= GIF_MAX_SECONDS:
                raise ValueError(
                    f"GIF duration must be between {GIF_MIN_SECONDS} and {GIF_MAX_SECONDS} seconds."
                )
        except ValueError as exc:
            messagebox.showerror("Invalid GIF settings", str(exc))
            return
        bilinear = bool(self.bilinear_var.get())

        gif_width, gif_height = gif_resolution
        total_frames = duration_seconds * GIF_FPS

        default_name = (
            f"random_pixels_{gif_width}x{gif_height}_{duration_seconds}s_"
            f"{GIF_FPS}fps_{depth}bit_{pixel_size}x{pixel_size}px_"
            f"{'bilinear' if bilinear else 'nearest'}.gif"
        )
        output_path = filedialog.asksaveasfilename(
            title="Export animated GIF",
            initialfile=default_name,
            defaultextension=".gif",
            filetypes=[("Animated GIF", "*.gif")],
        )
        if not output_path:
            return

        self.is_exporting_gif = True
        self.current_gif_duration = duration_seconds
        self.current_gif_resolution = gif_resolution
        self.current_gif_frames = total_frames
        self._set_action_buttons()
        self.progress.configure(maximum=total_frames, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.status_var.set(
            f"Exporting GIF: {gif_width} × {gif_height}, "
            f"{duration_seconds} seconds, {GIF_FPS} FPS ({total_frames} frames), "
            f"{depth}-bit source, {pixel_size}×{pixel_size} pixel blocks, "
            f"{'bilinear filtering' if bilinear else 'sharp pixel blocks'}..."
        )

        threading.Thread(
            target=self._gif_worker,
            args=(
                output_path, depth, pixel_size, bilinear,
                duration_seconds, gif_resolution,
            ),
            daemon=True,
        ).start()

    def _gif_worker(
        self, output_path, depth, pixel_size, bilinear,
        duration_seconds, gif_resolution,
    ):
        try:
            def report_progress(frame_number):
                self.gif_queue.put(("progress", frame_number))

            encode_random_gif(
                output_path,
                depth,
                pixel_size=pixel_size,
                duration_seconds=duration_seconds,
                bilinear=bilinear,
                progress_callback=report_progress,
                resolution=gif_resolution,
            )
            self.gif_queue.put(("success", output_path))
        except Exception as exc:
            self.gif_queue.put(("error", str(exc)))

    def _poll_gif_result(self):
        try:
            while True:
                result = self.gif_queue.get_nowait()
                if result[0] == "progress":
                    completed = result[1]
                    self.progress.configure(value=completed)
                    self.status_var.set(
                        f"Encoding GIF: frame {completed}/{self.current_gif_frames} "
                        f"({completed / GIF_FPS:.2f}/{self.current_gif_duration} seconds)"
                    )
                elif result[0] == "success":
                    self.is_exporting_gif = False
                    self.progress.configure(value=self.current_gif_frames)
                    self._set_action_buttons()
                    self.status_var.set(f"Saved animated GIF: {result[1]}")
                    messagebox.showinfo(
                        "GIF export complete",
                        f"Your {self.current_gif_resolution[0]} × "
                        f"{self.current_gif_resolution[1]}, "
                        f"{self.current_gif_duration}-second animated GIF "
                        f"({self.current_gif_frames} frames, 30 FPS average) has been saved:\n\n"
                        + result[1],
                    )
                    self.progress.pack_forget()
                elif result[0] == "error":
                    self.is_exporting_gif = False
                    self._set_action_buttons()
                    self.progress.pack_forget()
                    self.status_var.set("GIF export failed.")
                    messagebox.showerror("GIF export failed", result[1])
        except queue.Empty:
            pass

        self.root.after(80, self._poll_gif_result)

    def _video_worker(
        self, output_path, width, height, depth, duration_seconds,
        fps, bitrate_kbps, pixel_size, bilinear
    ):
        try:
            def report_progress(frame_number):
                self.video_queue.put(("progress", frame_number))

            encode_random_h264_video(
                output_path,
                width,
                height,
                depth,
                duration_seconds=duration_seconds,
                fps=fps,
                bitrate_kbps=bitrate_kbps,
                pixel_size=pixel_size,
                bilinear=bilinear,
                progress_callback=report_progress,
            )
            self.video_queue.put(("success", output_path))
        except Exception as exc:
            self.video_queue.put(("error", str(exc)))

    def _poll_video_result(self):
        try:
            while True:
                result = self.video_queue.get_nowait()
                if result[0] == "progress":
                    completed = result[1]
                    self.progress.configure(value=completed)
                    self.status_var.set(
                        f"Encoding H.264: frame {completed}/{self.current_video_frames} "
                        f"({completed / self.current_video_fps:.1f}/"
                        f"{self.current_video_duration} seconds)"
                    )
                elif result[0] == "success":
                    self.is_exporting_video = False
                    self.progress.configure(value=self.current_video_frames)
                    self._set_action_buttons()
                    self.status_var.set(f"Saved H.264 MP4: {result[1]}")
                    messagebox.showinfo(
                        "Video export complete",
                        f"Your {self.current_video_duration}-second, "
                        f"{self.current_video_fps}-fps H.264 MP4 video has been saved:\n\n"
                        + result[1],
                    )
                    self.progress.pack_forget()
                elif result[0] == "error":
                    self.is_exporting_video = False
                    self._set_action_buttons()
                    self.progress.pack_forget()
                    self.status_var.set("Video export failed.")
                    messagebox.showerror("Video export failed", result[1])
        except queue.Empty:
            pass

        self.root.after(80, self._poll_video_result)

    def _set_action_buttons(self):
        busy = self.is_generating or self.is_exporting_video or self.is_exporting_gif
        self.generate_button.configure(state="disabled" if busy else "normal")
        self.fractal_button.configure(state="disabled" if busy else "normal")
        self.video_button.configure(state="disabled" if busy else "normal")
        self.gif_button.configure(state="disabled" if busy else "normal")
        self.duration_scale.configure(state="disabled" if busy else "normal")
        self.fps_scale.configure(state="disabled" if busy else "normal")
        self.gif_duration_scale.configure(state="disabled" if busy else "normal")
        self.gif_resolution_combo.configure(state="disabled" if busy else "readonly")
        self.resolution_combo.configure(state="disabled" if busy else "readonly")
        self.pixel_size_scale.configure(state="disabled" if busy else "normal")
        self.depth_combo.configure(state="disabled" if busy else "readonly")
        self.bilinear_check.configure(state="disabled" if busy else "normal")
        self.save_button.configure(
            state="normal" if self.image is not None and not busy else "disabled"
        )

    def show_preview(self):
        if self.image is None:
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        preview = self.image.copy()
        preview.thumbnail(
            (max(1, canvas_width - 20), max(1, canvas_height - 20)),
            Image.Resampling.NEAREST,
        )
        self.preview_photo = ImageTk.PhotoImage(preview.convert("RGB"))
        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.preview_photo,
            anchor="center",
        )

    def on_resize(self, _event):
        self.show_preview()

    def save_image(self):
        if self.image is None:
            return

        filename = filedialog.asksaveasfilename(
            title="Save generated image",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            self.image.save(filename, "PNG", optimize=False)
            self.status_var.set(f"Saved PNG: {filename}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))


if __name__ == "__main__":
    app_window = tk.Tk()
    try:
        RandomPixelGenerator(app_window)
    except RuntimeError as exc:
        app_window.withdraw()
        messagebox.showerror("Missing application dependency", str(exc))
        app_window.destroy()
        raise SystemExit(1)
    app_window.mainloop()
