import json
import math
import os
import platform
import re
import shutil
import uuid
from datetime import datetime
import queue
import random
import statistics
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import imageio_ffmpeg
import numba
import numpy as np
from numba import njit, prange
from PIL import GifImagePlugin, Image, ImageColor, ImageTk

try:
    import pyopencl as cl
    OPENCL_IMPORT_ERROR = None
except Exception as _opencl_import_exc:
    # CPU-only machines can still run the application; explicit GPU selection
    # reports a clear diagnostic, while Automatic mode uses the Numba CPU.
    cl = None
    OPENCL_IMPORT_ERROR = f"{type(_opencl_import_exc).__name__}: {_opencl_import_exc}"

try:
    import ttkbootstrap
except ImportError:  # GUI startup reports a clear message if themes are unavailable.
    ttkbootstrap = None


class VideoExportCancelled(Exception):
    """Raised internally when the user cancels an active video export."""


class VideoExportControl:
    """Thread-safe cancellation token that can also stop the active FFmpeg process."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._process = None

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self.cancelled:
            raise VideoExportCancelled("Video export cancelled by user.")

    def attach_process(self, process):
        with self._lock:
            self._process = process
            should_terminate = self._event.is_set()
        if should_terminate:
            self._terminate_process(process)

    def detach_process(self, process=None):
        with self._lock:
            if process is None or self._process is process:
                self._process = None

    @staticmethod
    def _terminate_process(process):
        try:
            if process is not None and process.poll() is None:
                process.terminate()
        except (OSError, ProcessLookupError):
            pass

    def cancel(self):
        """Signal cancellation and terminate FFmpeg to unblock any pipe write."""
        self._event.set()
        with self._lock:
            process = self._process
        self._terminate_process(process)


def _cleanup_video_process(process, timeout=5):
    """Terminate/reap FFmpeg and close its streams without leaking handles."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
        # Always wait, even when poll() reports an exit code, so the OS has
        # fully reaped the child and released its output-file handle.
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=timeout)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        try:
            if stream is not None and not stream.closed:
                stream.close()
        except (OSError, ValueError):
            pass


def _remove_incomplete_video_file(output_path, retries=40, delay=0.25):
    """Reliably remove a cancelled/failed MP4 after FFmpeg releases its handle.

    Windows can briefly keep the just-closed output locked by the process
    teardown, antivirus scanning or thumbnail/indexing services. Retry sharing
    violations and clear the read-only attribute before giving up. Returns
    (removed, error_text) so the GUI never claims deletion succeeded falsely.
    """
    if not output_path:
        return True, None
    path = os.path.abspath(os.fspath(output_path))
    last_error = None
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            if not os.path.exists(path):
                return True, None
            try:
                # On Windows this also clears a read-only file attribute.
                os.chmod(path, 0o666)
            except OSError:
                pass
            os.remove(path)
            return True, None
        except FileNotFoundError:
            return True, None
        except OSError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(max(0.0, float(delay)))
    try:
        still_exists = os.path.exists(path)
    except OSError:
        still_exists = True
    if not still_exists:
        return True, None
    return False, str(last_error or "The incomplete video file still exists.")


IMAGE_MAX_SIDE = 20000
IMAGE_MAX_PIXELS = 100_000_000
VIDEO_MAX_PIXELS = 8_294_400  # 3840 × 2160
VIDEO_FPS_OPTIONS = (30, 60, 120)
COLOR_DEPTH_OPTIONS = (1, 2, 4, 8, 16, 24)
VIDEO_DEFAULT_FPS = 60
VIDEO_DEFAULT_SECONDS = 10
VIDEO_MIN_SECONDS = 1
VIDEO_MAX_SECONDS = 60
VIDEO_DEFAULT_BITRATE_KBPS = 200000  # Fixed target for all bitrate-controlled exports
VIDEO_QUALITY_MODE_QP = 12  # H.264 constant-quality level for random 1x1 video
VIDEO_HEVC_QUALITY_MODE_CQ = 20  # Higher HEVC CQ reduces oversized 1x1 random-noise files
VIDEO_HEVC_QUALITY_MODE_MAXRATE_KBPS = VIDEO_DEFAULT_BITRATE_KBPS  # 200 Mbit/s playback-friendly ceiling
VIDEO_CODEC_OPTIONS = ("H.264", "H.265/HEVC")
VIDEO_DEFAULT_CODEC = "H.265/HEVC"
VIDEO_MAX_ROTATION_DEGREES = 720
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

# Available escape-time fractal families. The default preserves the original
# randomized Mandelbrot generator; the others use the same color-depth and
# preview pipeline.
FRACTAL_TYPE_OPTIONS = (
    "Mandelbrot",
    "Julia Set",
    "Burning Ship",
    "Tricorn (Mandelbar)",
    "Multibrot (Power 3)",
    "Celtic Mandelbrot",
    "Phoenix",
)
DEFAULT_FRACTAL_TYPE = "Mandelbrot"

RENDERING_MODE_OPTIONS = ("Automatic", "CPU", "GPU")
DEFAULT_RENDERING_MODE = "Automatic"
OPENCL_TUNING_VERSION = 2
OPENCL_BENCH_ITERATIONS = 128
OPENCL_BENCH_REPEATS = 3
OPENCL_GPU_CHUNK_ROWS = 256
_OPENCL_RENDERER_CACHE = {}
_OPENCL_RENDERER_LOCK = threading.Lock()
_RENDER_BACKEND_TUNING_LOCK = threading.Lock()

# Automatic Numba thread tuning. Calibration is done once per CPU/Numba
# configuration and saved in the user's settings directory. Numba's thread
# mask is thread-local, so the selected count is applied inside every image
# worker thread immediately before fractal rendering.
NUMBA_THREAD_TUNING_VERSION = 1
NUMBA_TUNING_BENCH_WIDTH = 1024
NUMBA_TUNING_BENCH_ROWS = 48  # Match the production renderer's row chunk size.
NUMBA_TUNING_BENCH_ITERATIONS = 96
NUMBA_TUNING_BENCH_REPEATS = 2
_NUMBA_THREAD_TUNING_LOCK = threading.Lock()

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



# Fractal workspace data is stored separately from the existing UI preferences.
MAX_FRACTAL_HISTORY = 100
MAX_GALLERY_ITEMS = 250
BATCH_GENERATION_COUNTS = (100, 1000)
ANIMATION_DEFAULT_SECONDS = 5
ANIMATION_DEFAULT_FPS = 30
ANIMATION_ZOOM_OPTIONS = (2, 5, 10, 25, 50, 100, 250, 500, 1000)


def get_fractal_workspace_dir():
    return os.path.join(os.path.dirname(get_window_position_path()), "FractalWorkspace")


def get_fractal_bookmarks_path():
    return os.path.join(get_fractal_workspace_dir(), "bookmarks.json")


def get_custom_palettes_path():
    return os.path.join(get_fractal_workspace_dir(), "custom_palettes.json")


def get_active_palette_path():
    return os.path.join(get_fractal_workspace_dir(), "active_palette.json")


def get_gallery_directory():
    return os.path.join(get_fractal_workspace_dir(), "Gallery")


def get_gallery_settings_path():
    return os.path.join(get_fractal_workspace_dir(), "gallery_settings.json")


def load_gallery_auto_save(path=None):
    path = path or get_gallery_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream).get("auto_save", True)
        return bool(value)
    except (OSError, ValueError, TypeError, AttributeError):
        return True


def save_gallery_auto_save(enabled, path=None):
    _atomic_write_json(path or get_gallery_settings_path(), {"auto_save": bool(enabled)})


def _atomic_write_json(path, value):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def load_fractal_bookmarks(path=None):
    path = path or get_fractal_bookmarks_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict) and isinstance(item.get("view_state"), dict)]
    except (OSError, ValueError, TypeError):
        return []


def save_fractal_bookmarks(bookmarks, path=None):
    path = path or get_fractal_bookmarks_path()
    if not isinstance(bookmarks, list):
        raise ValueError("Bookmarks must be a list.")
    _atomic_write_json(path, bookmarks)


def normalize_palette_stops(stops):
    """Validate and normalize a list of two or more hexadecimal RGB stops."""
    if not isinstance(stops, (list, tuple)) or not 2 <= len(stops) <= 16:
        raise ValueError("A custom gradient must contain between 2 and 16 color stops.")
    normalized = []
    for stop in stops:
        if not isinstance(stop, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", stop.strip()):
            raise ValueError(f"Invalid color stop {stop!r}; use #RRGGBB format.")
        normalized.append(stop.strip().upper())
    return normalized


def load_custom_palettes(path=None):
    path = path or get_custom_palettes_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            return {}
        result = {}
        for name, stops in raw.items():
            if isinstance(name, str) and name.strip():
                try:
                    result[name.strip()] = normalize_palette_stops(stops)
                except ValueError:
                    continue
        return result
    except (OSError, ValueError, TypeError):
        return {}


def save_custom_palettes(palettes, path=None):
    path = path or get_custom_palettes_path()
    if not isinstance(palettes, dict):
        raise ValueError("Custom palettes must be a dictionary.")
    clean = {}
    for name, stops in palettes.items():
        clean_name = str(name).strip()
        if not clean_name or clean_name.lower() == "random":
            raise ValueError("Choose a palette name other than 'Random'.")
        clean[clean_name] = normalize_palette_stops(stops)
    _atomic_write_json(path, clean)


def load_active_palette(path=None):
    path = path or get_active_palette_path()
    try:
        with open(path, "r", encoding="utf-8") as stream:
            name = json.load(stream).get("name", "Random")
        return name if isinstance(name, str) else "Random"
    except (OSError, ValueError, TypeError, AttributeError):
        return "Random"


def save_active_palette(name, path=None):
    path = path or get_active_palette_path()
    _atomic_write_json(path, {"name": str(name)})


def sample_custom_palette(stops, count=256):
    """Sample an RGB gradient into a uint8 lookup table."""
    clean = normalize_palette_stops(stops)
    colors = np.asarray([ImageColor.getrgb(color) for color in clean], dtype=np.float32)
    source_positions = np.linspace(0.0, 1.0, len(colors), dtype=np.float32)
    target_positions = np.linspace(0.0, 1.0, int(count), dtype=np.float32)
    table = np.stack([
        np.interp(target_positions, source_positions, colors[:, channel])
        for channel in range(3)
    ], axis=1)
    return np.rint(table).clip(0, 255).astype(np.uint8)


def save_gallery_entry(image, metadata, gallery_dir=None, max_items=MAX_GALLERY_ITEMS):
    """Save a PNG plus JSON metadata and prune the oldest gallery entries."""
    gallery_dir = gallery_dir or get_gallery_directory()
    os.makedirs(gallery_dir, exist_ok=True)
    entry_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"
    image_name = entry_id + ".png"
    metadata_name = entry_id + ".json"
    image_path = os.path.join(gallery_dir, image_name)
    metadata_path = os.path.join(gallery_dir, metadata_name)
    image.save(image_path, "PNG", optimize=False)
    record = dict(metadata)
    record.update({"id": entry_id, "image_file": image_name, "created": datetime.now().isoformat(timespec="seconds")})
    _atomic_write_json(metadata_path, record)

    entries = []
    for filename in os.listdir(gallery_dir):
        if filename.endswith(".json"):
            path = os.path.join(gallery_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as stream:
                    item = json.load(stream)
                entries.append((str(item.get("created", "")), path, item))
            except (OSError, ValueError, TypeError):
                continue
    entries.sort(key=lambda item: item[0], reverse=True)
    for _created, old_meta_path, old_item in entries[max(1, int(max_items)):]:
        try:
            os.remove(old_meta_path)
            old_image = os.path.join(gallery_dir, str(old_item.get("image_file", "")))
            if os.path.isfile(old_image):
                os.remove(old_image)
        except OSError:
            pass
    return record


def list_gallery_entries(gallery_dir=None):
    gallery_dir = gallery_dir or get_gallery_directory()
    entries = []
    if not os.path.isdir(gallery_dir):
        return entries
    for filename in os.listdir(gallery_dir):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(gallery_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as stream:
                item = json.load(stream)
            image_path = os.path.join(gallery_dir, str(item.get("image_file", "")))
            if os.path.isfile(image_path) and isinstance(item.get("view_state"), dict):
                item["metadata_file"] = path
                item["image_path"] = image_path
                entries.append(item)
        except (OSError, ValueError, TypeError):
            continue
    entries.sort(key=lambda item: str(item.get("created", "")), reverse=True)
    return entries

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


def get_rendering_mode_preference_path():
    """Return the user-profile path for the selected CPU/GPU render mode."""
    return os.path.join(
        os.path.dirname(get_window_position_path()), "rendering_mode_preference.json"
    )


def load_rendering_mode_preference(path=None):
    """Load Automatic, CPU or GPU, defaulting safely to Automatic."""
    path = path or get_rendering_mode_preference_path()
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            value = json.load(settings_file).get("mode")
        if value in RENDERING_MODE_OPTIONS:
            return value
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DEFAULT_RENDERING_MODE


def save_rendering_mode_preference(mode, path=None):
    """Persist a valid render mode without changing other application settings."""
    if mode not in RENDERING_MODE_OPTIONS:
        raise ValueError(f"Unsupported rendering mode: {mode!r}")
    path = path or get_rendering_mode_preference_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as settings_file:
            json.dump({"mode": mode}, settings_file, indent=2)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def get_render_backend_tuning_path():
    """Return the cache path for measured CPU-vs-GPU backend choices."""
    return os.path.join(
        os.path.dirname(get_window_position_path()), "render_backend_tuning.json"
    )


def list_opencl_gpu_devices():
    """Return available OpenCL GPU devices, preferring NVIDIA discrete GPUs."""
    if cl is None:
        return [], (
            "PyOpenCL is not installed or could not be loaded. Rebuild with the "
            "provided build_windows.bat, which installs PyOpenCL. "
            f"Import detail: {OPENCL_IMPORT_ERROR}"
        )
    try:
        devices = []
        for platform_item in cl.get_platforms():
            try:
                platform_devices = platform_item.get_devices(
                    device_type=cl.device_type.GPU
                )
            except Exception:
                continue
            for device in platform_devices:
                # The OpenCL backend uses double precision to match the CPU
                # renderer's coordinate and escape-time calculations.
                extensions = set(str(getattr(device, "extensions", "")).split())
                double_config = getattr(device, "double_fp_config", 0)
                if not double_config and "cl_khr_fp64" not in extensions:
                    continue
                devices.append(device)
        devices.sort(
            key=lambda d: (
                "nvidia" not in str(getattr(d, "vendor", "")).lower()
                and "nvidia" not in str(getattr(d, "name", "")).lower(),
                str(getattr(d, "name", "")).lower(),
            )
        )
        if not devices:
            return [], (
                "No OpenCL GPU with double-precision support was found. Install or "
                "update the graphics-card vendor driver. NVIDIA GPUs require a "
                "supported GeForce driver with its OpenCL runtime."
            )
        return devices, None
    except Exception as exc:
        return [], (
            "OpenCL could not enumerate graphics devices. Check that the GPU driver "
            f"and its OpenCL runtime are installed. Details: {type(exc).__name__}: {exc}"
        )


def opencl_device_label(device):
    """Return a concise, readable vendor/device label."""
    vendor = str(getattr(device, "vendor", "OpenCL" )).strip()
    name = str(getattr(device, "name", "GPU" )).strip()
    return f"{vendor} {name}".strip()


OPENCL_FRACTAL_KERNEL_SOURCE = r"""
#pragma OPENCL EXTENSION cl_khr_fp64 : enable

__kernel void fractal_escape(
    __global const double *x_coordinates,
    __global const double *y_coordinates,
    __global float *smooth_iterations,
    __global uchar *escaped,
    const int width,
    const int row_offset,
    const int chunk_height,
    const int fractal_code,
    const int max_iterations,
    const double julia_c_real,
    const double julia_c_imag,
    const double phoenix_p_real,
    const double phoenix_p_imag)
{
    const int x = (int)get_global_id(0);
    const int local_y = (int)get_global_id(1);
    if (x >= width || local_y >= chunk_height) return;

    const int index = local_y * width + x;
    const int y = row_offset + local_y;
    const double cr_coordinate = x_coordinates[x];
    const double ci_coordinate = y_coordinates[y];
    smooth_iterations[index] = 0.0f;
    escaped[index] = (uchar)0;

    const double degree_log = (fractal_code == 4) ? log(3.0) : log(2.0);

    if (fractal_code == 0) {
        const double qx = cr_coordinate - 0.25;
        const double q = qx * qx + ci_coordinate * ci_coordinate;
        const int in_main_cardioid =
            q * (q + qx) <= 0.25 * ci_coordinate * ci_coordinate;
        const double bx = cr_coordinate + 1.0;
        const int in_period_two_bulb =
            bx * bx + ci_coordinate * ci_coordinate <= 0.0625;
        if (in_main_cardioid || in_period_two_bulb) return;
    }

    double zr;
    double zi;
    double cr;
    double ci;
    if (fractal_code == 1) {
        zr = cr_coordinate;
        zi = ci_coordinate;
        cr = julia_c_real;
        ci = julia_c_imag;
    } else {
        zr = 0.0;
        zi = 0.0;
        cr = cr_coordinate;
        ci = ci_coordinate;
    }

    double previous_real = 0.0;
    double previous_imag = 0.0;
    for (int iteration = 0; iteration < max_iterations; ++iteration) {
        double next_real;
        double next_imag;

        if (fractal_code == 2) {
            const double ar = fabs(zr);
            const double ai = fabs(zi);
            next_real = ar * ar - ai * ai + cr;
            next_imag = 2.0 * ar * ai + ci;
        } else if (fractal_code == 3) {
            next_real = zr * zr - zi * zi + cr;
            next_imag = -2.0 * zr * zi + ci;
        } else if (fractal_code == 4) {
            next_real = zr * zr * zr - 3.0 * zr * zi * zi + cr;
            next_imag = 3.0 * zr * zr * zi - zi * zi * zi + ci;
        } else if (fractal_code == 5) {
            next_real = fabs(zr * zr - zi * zi) + cr;
            next_imag = 2.0 * zr * zi + ci;
        } else if (fractal_code == 6) {
            next_real = zr * zr - zi * zi + cr
                + phoenix_p_real * previous_real - phoenix_p_imag * previous_imag;
            next_imag = 2.0 * zr * zi + ci
                + phoenix_p_real * previous_imag + phoenix_p_imag * previous_real;
            previous_real = zr;
            previous_imag = zi;
        } else {
            next_real = zr * zr - zi * zi + cr;
            next_imag = 2.0 * zr * zi + ci;
        }

        const double magnitude_squared = next_real * next_real + next_imag * next_imag;
        zr = next_real;
        zi = next_imag;
        if (magnitude_squared > 4.0) {
            const double magnitude = sqrt(magnitude_squared);
            double smooth_value = (double)iteration + 1.0
                - log(log(magnitude)) / degree_log;
            if (smooth_value < 0.0) smooth_value = 0.0;
            else if (smooth_value > (double)max_iterations)
                smooth_value = (double)max_iterations;
            smooth_iterations[index] = (float)smooth_value;
            escaped[index] = (uchar)1;
            break;
        }
    }
}

/* Full-pipeline kernel: computes escape iterations and writes final indexed or
   RGB pixels directly on the device. This avoids transferring two large
   intermediate arrays and avoids CPU-side per-pixel HSV conversion. */
__kernel void fractal_render(
    __global const double *x_coordinates,
    __global const double *y_coordinates,
    __global uchar *output_pixels,
    const int width,
    const int fractal_code,
    const int max_iterations,
    const double julia_c_real,
    const double julia_c_imag,
    const double phoenix_p_real,
    const double phoenix_p_imag,
    const int depth,
    const int color_count,
    const float palette_phase,
    const float palette_cycles,
    __global const uchar *custom_palette_rgb,
    const int custom_palette_count,
    const int red_bits,
    const int green_bits,
    const int blue_bits)
{
    const int x = (int)get_global_id(0);
    const int y = (int)get_global_id(1);
    const int height = (int)get_global_size(1);
    if (x >= width || y >= height) return;

    const int pixel_index = y * width + x;
    const int output_channels = (depth <= 8) ? 1 : 3;
    const int output_index = pixel_index * output_channels;
    const double cr_coordinate = x_coordinates[x];
    const double ci_coordinate = y_coordinates[y];
    const double degree_log = (fractal_code == 4) ? log(3.0) : log(2.0);

    int escaped = 0;
    float smooth_value = 0.0f;

    if (fractal_code == 0) {
        const double qx = cr_coordinate - 0.25;
        const double q = qx * qx + ci_coordinate * ci_coordinate;
        const int in_main_cardioid =
            q * (q + qx) <= 0.25 * ci_coordinate * ci_coordinate;
        const double bx = cr_coordinate + 1.0;
        const int in_period_two_bulb =
            bx * bx + ci_coordinate * ci_coordinate <= 0.0625;
        if (in_main_cardioid || in_period_two_bulb) {
            output_pixels[output_index] = (uchar)0;
            if (output_channels == 3) {
                output_pixels[output_index + 1] = (uchar)0;
                output_pixels[output_index + 2] = (uchar)0;
            }
            return;
        }
    }

    double zr;
    double zi;
    double cr;
    double ci;
    if (fractal_code == 1) {
        zr = cr_coordinate;
        zi = ci_coordinate;
        cr = julia_c_real;
        ci = julia_c_imag;
    } else {
        zr = 0.0;
        zi = 0.0;
        cr = cr_coordinate;
        ci = ci_coordinate;
    }

    double previous_real = 0.0;
    double previous_imag = 0.0;
    for (int iteration = 0; iteration < max_iterations; ++iteration) {
        double next_real;
        double next_imag;

        if (fractal_code == 2) {
            const double ar = fabs(zr);
            const double ai = fabs(zi);
            next_real = ar * ar - ai * ai + cr;
            next_imag = 2.0 * ar * ai + ci;
        } else if (fractal_code == 3) {
            next_real = zr * zr - zi * zi + cr;
            next_imag = -2.0 * zr * zi + ci;
        } else if (fractal_code == 4) {
            next_real = zr * zr * zr - 3.0 * zr * zi * zi + cr;
            next_imag = 3.0 * zr * zr * zi - zi * zi * zi + ci;
        } else if (fractal_code == 5) {
            next_real = fabs(zr * zr - zi * zi) + cr;
            next_imag = 2.0 * zr * zi + ci;
        } else if (fractal_code == 6) {
            next_real = zr * zr - zi * zi + cr
                + phoenix_p_real * previous_real - phoenix_p_imag * previous_imag;
            next_imag = 2.0 * zr * zi + ci
                + phoenix_p_real * previous_imag + phoenix_p_imag * previous_real;
            previous_real = zr;
            previous_imag = zi;
        } else {
            next_real = zr * zr - zi * zi + cr;
            next_imag = 2.0 * zr * zi + ci;
        }

        const double magnitude_squared = next_real * next_real + next_imag * next_imag;
        zr = next_real;
        zi = next_imag;
        if (magnitude_squared > 4.0) {
            const double magnitude = sqrt(magnitude_squared);
            double smooth = (double)iteration + 1.0
                - log(log(magnitude)) / degree_log;
            if (smooth < 0.0) smooth = 0.0;
            else if (smooth > (double)max_iterations)
                smooth = (double)max_iterations;
            smooth_value = (float)smooth;
            escaped = 1;
            break;
        }
    }

    if (depth <= 8) {
        if (!escaped) {
            output_pixels[output_index] = (uchar)0;
        } else if (depth == 1) {
            output_pixels[output_index] = (uchar)1;
        } else {
            const float normalized = clamp(
                smooth_value / (float)max_iterations, 0.0f, 1.0f);
            const int maximum_index = color_count - 2;
            int palette_index = 1 + (int)(normalized * (float)maximum_index);
            if (palette_index > color_count - 1)
                palette_index = color_count - 1;
            output_pixels[output_index] = (uchar)palette_index;
        }
        return;
    }

    if (!escaped) {
        output_pixels[output_index] = (uchar)0;
        output_pixels[output_index + 1] = (uchar)0;
        output_pixels[output_index + 2] = (uchar)0;
        return;
    }

    const float normalized = clamp(
        smooth_value / (float)max_iterations, 0.0f, 1.0f);
    float red;
    float green;
    float blue;
    if (custom_palette_count >= 2) {
        const float palette_position = normalized * (float)(custom_palette_count - 1);
        const int lower = min((int)floor(palette_position), custom_palette_count - 1);
        const int upper = min(lower + 1, custom_palette_count - 1);
        const float blend = palette_position - (float)lower;
        red = mix((float)custom_palette_rgb[lower * 3], (float)custom_palette_rgb[upper * 3], blend) / 255.0f;
        green = mix((float)custom_palette_rgb[lower * 3 + 1], (float)custom_palette_rgb[upper * 3 + 1], blend) / 255.0f;
        blue = mix((float)custom_palette_rgb[lower * 3 + 2], (float)custom_palette_rgb[upper * 3 + 2], blend) / 255.0f;
    } else {
        float hue = fmod(palette_phase + normalized * palette_cycles, 1.0f);
        if (hue < 0.0f) hue += 1.0f;
        const float h6 = hue * 6.0f;
        const int sector = (int)floor(h6);
        const float fraction = h6 - floor(h6);
        const float p = 0.08f;
        const float q = 1.0f - 0.92f * fraction;
        const float t = 0.08f + 0.92f * fraction;
        if (sector == 0) { red = 1.0f; green = t; blue = p; }
        else if (sector == 1) { red = q; green = 1.0f; blue = p; }
        else if (sector == 2) { red = p; green = 1.0f; blue = t; }
        else if (sector == 3) { red = p; green = q; blue = 1.0f; }
        else if (sector == 4) { red = t; green = p; blue = 1.0f; }
        else { red = 1.0f; green = p; blue = q; }
    }

    const int channel_bits[3] = {red_bits, green_bits, blue_bits};
    const float channels[3] = {red, green, blue};
    for (int channel = 0; channel < 3; ++channel) {
        const uchar rgb8 = convert_uchar_sat_rte(clamp(channels[channel], 0.0f, 1.0f) * 255.0f);
        const int levels = (1 << channel_bits[channel]) - 1;
        const float quantized = rint((float)rgb8 * (float)levels / 255.0f);
        const float restored = rint(quantized * 255.0f / (float)levels);
        output_pixels[output_index + channel] = convert_uchar_sat_rte(restored);
    }
}
"""


OPENCL_VIDEO_KERNEL_SOURCE = r"""
inline uint pg_hash_u32(uint value)
{
    value ^= value >> 16;
    value *= 0x7feb352dU;
    value ^= value >> 15;
    value *= 0x846ca68bU;
    value ^= value >> 16;
    return value;
}

inline float3 pg_random_cell_color(
    const int cell_x,
    const int cell_y,
    const int frame_number,
    const int depth,
    const int color_count,
    const int red_bits,
    const int green_bits,
    const int blue_bits,
    __global const uchar *palette,
    const uint seed)
{
    uint base = seed
        ^ ((uint)frame_number * 0x9e3779b9U)
        ^ ((uint)cell_x * 0x85ebca6bU)
        ^ ((uint)cell_y * 0xc2b2ae35U);
    if (depth <= 8) {
        const uint index = pg_hash_u32(base) % (uint)color_count;
        const int offset = (int)index * 3;
        return (float3)(
            (float)palette[offset],
            (float)palette[offset + 1],
            (float)palette[offset + 2]);
    }

    const int red_max = (1 << red_bits) - 1;
    const int green_max = (1 << green_bits) - 1;
    const int blue_max = (1 << blue_bits) - 1;
    const uint rv = pg_hash_u32(base ^ 0x68bc21ebU) % (uint)(red_max + 1);
    const uint gv = pg_hash_u32(base ^ 0x02e5be93U) % (uint)(green_max + 1);
    const uint bv = pg_hash_u32(base ^ 0x967a889bU) % (uint)(blue_max + 1);
    const uint red = (rv * 255U + (uint)(red_max / 2)) / (uint)red_max;
    const uint green = (gv * 255U + (uint)(green_max / 2)) / (uint)green_max;
    const uint blue = (bv * 255U + (uint)(blue_max / 2)) / (uint)blue_max;
    return (float3)((float)red, (float)green, (float)blue);
}

inline float3 pg_grid_sample(
    const float grid_x,
    const float grid_y,
    const int frame_number,
    const int depth,
    const int color_count,
    const int red_bits,
    const int green_bits,
    const int blue_bits,
    const int grid_width,
    const int grid_height,
    __global const uchar *palette,
    const uint seed)
{
    const float clamped_x = clamp(grid_x, 0.0f, (float)(grid_width - 1));
    const float clamped_y = clamp(grid_y, 0.0f, (float)(grid_height - 1));
    const int x0 = (int)floor(clamped_x);
    const int y0 = (int)floor(clamped_y);
    const int x1 = min(x0 + 1, grid_width - 1);
    const int y1 = min(y0 + 1, grid_height - 1);
    const float tx = clamped_x - (float)x0;
    const float ty = clamped_y - (float)y0;
    const float3 c00 = pg_random_cell_color(x0, y0, frame_number, depth,
        color_count, red_bits, green_bits, blue_bits, palette, seed);
    const float3 c10 = pg_random_cell_color(x1, y0, frame_number, depth,
        color_count, red_bits, green_bits, blue_bits, palette, seed);
    const float3 c01 = pg_random_cell_color(x0, y1, frame_number, depth,
        color_count, red_bits, green_bits, blue_bits, palette, seed);
    const float3 c11 = pg_random_cell_color(x1, y1, frame_number, depth,
        color_count, red_bits, green_bits, blue_bits, palette, seed);
    return mix(mix(c00, c10, tx), mix(c01, c11, tx), ty);
}

inline float3 pg_random_source_pixel(
    const int x,
    const int y,
    const int frame_number,
    const int width,
    const int height,
    const int depth,
    const int pixel_size,
    const int bilinear,
    const int color_count,
    const int red_bits,
    const int green_bits,
    const int blue_bits,
    const int grid_width,
    const int grid_height,
    __global const uchar *palette,
    const uint seed)
{
    if (x < 0 || x >= width || y < 0 || y >= height)
        return (float3)(0.0f, 0.0f, 0.0f);

    if (!bilinear) {
        return pg_random_cell_color(
            x / pixel_size, y / pixel_size, frame_number, depth, color_count,
            red_bits, green_bits, blue_bits, palette, seed);
    }

    // Match the pixel-center mapping used by Pillow's bilinear resize.
    const float gx = ((float)x + 0.5f) * (float)grid_width / (float)width - 0.5f;
    const float gy = ((float)y + 0.5f) * (float)grid_height / (float)height - 0.5f;
    return pg_grid_sample(gx, gy, frame_number, depth, color_count,
        red_bits, green_bits, blue_bits, grid_width, grid_height, palette, seed);
}

__kernel void pg_random_rotated_video_frames(
    __global uchar *output_pixels,
    const int width,
    const int height,
    const int depth,
    const int pixel_size,
    const int bilinear,
    const int color_count,
    const int red_bits,
    const int green_bits,
    const int blue_bits,
    const int grid_width,
    const int grid_height,
    __global const uchar *palette,
    const uint seed,
    const int first_frame,
    const int total_frames,
    const float rotation_degrees,
    const float direction_sign)
{
    const int x = (int)get_global_id(0);
    const int y = (int)get_global_id(1);
    const int batch_frame = (int)get_global_id(2);
    const int batch_count = (int)get_global_size(2);
    if (x >= width || y >= height || batch_frame >= batch_count) return;

    const int frame_number = first_frame + batch_frame;
    const float progress = (total_frames <= 1) ? 1.0f
        : (float)frame_number / (float)(total_frames - 1);
    const float angle = rotation_degrees * direction_sign * progress
        * 0.01745329251994329577f;
    const float cs = cos(angle);
    const float sn = sin(angle);
    const float center_x = ((float)width - 1.0f) * 0.5f;
    const float center_y = ((float)height - 1.0f) * 0.5f;
    const float dx = (float)x - center_x;
    const float dy = (float)y - center_y;
    // Inverse transform: positive angle is visually clockwise in image coordinates.
    const float source_x = center_x + cs * dx + sn * dy;
    const float source_y = center_y - sn * dx + cs * dy;
    // Random pixel art is high-frequency by design. Bilinear rotation blends
    // neighboring random colors as soon as the angle becomes non-zero, which
    // visibly washes out the image and reduces contrast from frame 2 onward.
    // Use nearest-neighbor for the geometric rotation so source colors remain
    // crisp. The separate `bilinear` option is still honored by
    // pg_random_source_pixel() when scaling the pixel grid.
    const int nearest_x = (int)floor(source_x + 0.5f);
    const int nearest_y = (int)floor(source_y + 0.5f);
    const float3 result = pg_random_source_pixel(
        nearest_x, nearest_y, frame_number, width, height, depth, pixel_size,
        bilinear, color_count, red_bits, green_bits, blue_bits,
        grid_width, grid_height, palette, seed);

    const int output_index = ((batch_frame * height + y) * width + x) * 3;
    output_pixels[output_index] = convert_uchar_sat_rte(result.x);
    output_pixels[output_index + 1] = convert_uchar_sat_rte(result.y);
    output_pixels[output_index + 2] = convert_uchar_sat_rte(result.z);
}

inline float3 pg_read_rgb(
    __global const uchar *input_pixels,
    const int frame_number,
    const int width,
    const int height,
    const int x,
    const int y)
{
    if (x < 0 || x >= width || y < 0 || y >= height)
        return (float3)(0.0f, 0.0f, 0.0f);
    const int index = ((frame_number * height + y) * width + x) * 3;
    return (float3)((float)input_pixels[index],
        (float)input_pixels[index + 1], (float)input_pixels[index + 2]);
}

__kernel void pg_rotate_rgb_video_frames(
    __global const uchar *input_pixels,
    __global uchar *output_pixels,
    const int width,
    const int height,
    const int first_frame,
    const int total_frames,
    const float rotation_degrees,
    const float direction_sign)
{
    const int x = (int)get_global_id(0);
    const int y = (int)get_global_id(1);
    const int batch_frame = (int)get_global_id(2);
    const int batch_count = (int)get_global_size(2);
    if (x >= width || y >= height || batch_frame >= batch_count) return;
    const int frame_number = first_frame + batch_frame;
    const float progress = (total_frames <= 1) ? 1.0f
        : (float)frame_number / (float)(total_frames - 1);
    const float angle = rotation_degrees * direction_sign * progress
        * 0.01745329251994329577f;
    const float cs = cos(angle);
    const float sn = sin(angle);
    const float cx = ((float)width - 1.0f) * 0.5f;
    const float cy = ((float)height - 1.0f) * 0.5f;
    const float dx = (float)x - cx;
    const float dy = (float)y - cy;
    const float sx = cx + cs * dx + sn * dy;
    const float sy = cy - sn * dx + cs * dy;
    const int x0 = (int)floor(sx);
    const int y0 = (int)floor(sy);
    const float tx = sx - (float)x0;
    const float ty = sy - (float)y0;
    const float3 c00 = pg_read_rgb(input_pixels, batch_frame, width, height, x0, y0);
    float3 result = c00;
    if (fabs(angle) > 1.0e-7f) {
        const float3 c10 = pg_read_rgb(input_pixels, batch_frame, width, height, x0 + 1, y0);
        const float3 c01 = pg_read_rgb(input_pixels, batch_frame, width, height, x0, y0 + 1);
        const float3 c11 = pg_read_rgb(input_pixels, batch_frame, width, height, x0 + 1, y0 + 1);
        result = mix(mix(c00, c10, tx), mix(c01, c11, tx), ty);
    }
    const int output_index = ((batch_frame * height + y) * width + x) * 3;
    output_pixels[output_index] = convert_uchar_sat_rte(result.x);
    output_pixels[output_index + 1] = convert_uchar_sat_rte(result.y);
    output_pixels[output_index + 2] = convert_uchar_sat_rte(result.z);
}
"""


class OpenCLFractalRenderer:
    """OpenCL escape-time renderer; one work-item computes one image pixel."""

    def __init__(self, device):
        if cl is None:
            raise RuntimeError(
                "PyOpenCL is unavailable. Rebuild Pixel Generator with the provided "
                "build_windows.bat and install a current NVIDIA graphics driver. "
                f"Details: {OPENCL_IMPORT_ERROR}"
            )
        self.device = device
        try:
            self.context = cl.Context(devices=[device])
            self.queue = cl.CommandQueue(self.context, device=device)
            self.program = cl.Program(
                self.context, OPENCL_FRACTAL_KERNEL_SOURCE
            ).build(options=["-cl-std=CL1.2"])
            self.kernel = cl.Kernel(self.program, "fractal_escape")
            self.render_kernel = cl.Kernel(self.program, "fractal_render")
        except Exception as exc:
            raise RuntimeError(
                f"Could not initialize OpenCL on {opencl_device_label(device)}. "
                "Update the GPU driver and verify that its OpenCL runtime is installed. "
                f"OpenCL details: {type(exc).__name__}: {exc}"
            ) from exc

    def _ensure_video_kernels(self):
        """Build the lightweight video kernels lazily on the selected OpenCL device."""
        if getattr(self, "video_program", None) is not None:
            return
        try:
            self.video_program = cl.Program(
                self.context, OPENCL_VIDEO_KERNEL_SOURCE
            ).build(options=["-cl-std=CL1.2"])
            self.random_video_kernel = cl.Kernel(
                self.video_program, "pg_random_rotated_video_frames"
            )
            self.rotate_video_kernel = cl.Kernel(
                self.video_program, "pg_rotate_rgb_video_frames"
            )
        except Exception as exc:
            self.video_program = None
            raise RuntimeError(
                f"Could not compile the OpenCL video kernels on "
                f"{opencl_device_label(self.device)}: {type(exc).__name__}: {exc}"
            ) from exc

    def render_random_video_batch(
        self, width, height, depth, pixel_size, bilinear, palette,
        seed, first_frame, total_frames, rotation_degrees,
        rotation_direction, batch_frames,
    ):
        """Generate fresh random frames and rotate them in one OpenCL pass."""
        self._ensure_video_kernels()
        width, height, depth = int(width), int(height), int(depth)
        pixel_size = int(pixel_size)
        first_frame, total_frames = int(first_frame), int(total_frames)
        batch_frames = int(batch_frames)
        palette = np.ascontiguousarray(palette, dtype=np.uint8).reshape(-1, 3)
        if width < 1 or height < 1 or batch_frames < 1:
            raise ValueError("OpenCL video frame dimensions and batch size must be positive.")
        grid_width = (width + pixel_size - 1) // pixel_size
        grid_height = (height + pixel_size - 1) // pixel_size
        channel_bits = _depth_channel_bits(depth) if depth > 8 else (8, 8, 8)
        direction_sign = 1.0 if str(rotation_direction) == "Clockwise" else -1.0
        flags = cl.mem_flags
        palette_key = palette.tobytes()
        if getattr(self, "_video_palette_key", None) != palette_key:
            self._video_palette_buffer = cl.Buffer(
                self.context, flags.READ_ONLY | flags.COPY_HOST_PTR, hostbuf=palette
            )
            self._video_palette_key = palette_key
        palette_buffer = self._video_palette_buffer
        required_bytes = batch_frames * width * height * 3
        if (getattr(self, "_random_video_output_buffer", None) is None
                or getattr(self, "_random_video_output_capacity", 0) < required_bytes):
            self._random_video_output_buffer = cl.Buffer(
                self.context, flags.WRITE_ONLY, size=required_bytes
            )
            self._random_video_output_capacity = required_bytes
        output_buffer = self._random_video_output_buffer
        self.random_video_kernel(
            self.queue, (width, height, batch_frames), None,
            output_buffer,
            np.int32(width), np.int32(height), np.int32(depth),
            np.int32(pixel_size), np.int32(bool(bilinear)),
            np.int32(len(palette)),
            np.int32(channel_bits[0]), np.int32(channel_bits[1]),
            np.int32(channel_bits[2]), np.int32(grid_width), np.int32(grid_height),
            palette_buffer, np.uint32(seed), np.int32(first_frame),
            np.int32(total_frames), np.float32(rotation_degrees),
            np.float32(direction_sign),
        )
        output = np.empty((batch_frames, height, width, 3), dtype=np.uint8)
        cl.enqueue_copy(self.queue, output, output_buffer, is_blocking=True)
        return output

    def rotate_rgb_batch(
        self, rgb_frames, first_frame, total_frames,
        rotation_degrees, rotation_direction,
    ):
        """Rotate one or more RGB frames on the OpenCL device."""
        self._ensure_video_kernels()
        frames = np.ascontiguousarray(rgb_frames, dtype=np.uint8)
        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError("RGB video batch must have shape (frames, height, width, 3).")
        batch_frames, height, width, _channels = frames.shape
        if batch_frames < 1 or width < 1 or height < 1:
            raise ValueError("OpenCL rotation batch must contain at least one image.")
        direction_sign = 1.0 if str(rotation_direction) == "Clockwise" else -1.0
        flags = cl.mem_flags
        required_bytes = frames.nbytes
        if (getattr(self, "_rotate_video_input_buffer", None) is None
                or getattr(self, "_rotate_video_buffer_capacity", 0) < required_bytes):
            self._rotate_video_input_buffer = cl.Buffer(
                self.context, flags.READ_ONLY, size=required_bytes
            )
            self._rotate_video_output_buffer = cl.Buffer(
                self.context, flags.WRITE_ONLY, size=required_bytes
            )
            self._rotate_video_buffer_capacity = required_bytes
        input_buffer = self._rotate_video_input_buffer
        output_buffer = self._rotate_video_output_buffer
        cl.enqueue_copy(self.queue, input_buffer, frames, is_blocking=False)
        self.rotate_video_kernel(
            self.queue, (width, height, batch_frames), None,
            input_buffer, output_buffer,
            np.int32(width), np.int32(height), np.int32(first_frame),
            np.int32(total_frames), np.float32(rotation_degrees),
            np.float32(direction_sign),
        )
        output = np.empty_like(frames)
        cl.enqueue_copy(self.queue, output, output_buffer, is_blocking=True)
        return output

    def iter_escape_chunks(
        self,
        x_coordinates,
        y_coordinates,
        fractal_code,
        max_iterations,
        julia_c_real,
        julia_c_imag,
        phoenix_p_real,
        phoenix_p_imag,
        chunk_rows=OPENCL_GPU_CHUNK_ROWS,
    ):
        """Yield (row_start, row_end, smooth, escaped) chunks from the GPU."""
        x_coordinates = np.ascontiguousarray(x_coordinates, dtype=np.float64)
        y_coordinates = np.ascontiguousarray(y_coordinates, dtype=np.float64)
        height = int(y_coordinates.size)
        width = int(x_coordinates.size)
        if width <= 0 or height <= 0:
            raise ValueError("OpenCL fractal dimensions must be positive.")
        chunk_rows = max(1, min(int(chunk_rows), height))
        flags = cl.mem_flags
        x_buffer = cl.Buffer(
            self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
            hostbuf=x_coordinates,
        )
        y_buffer = cl.Buffer(
            self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
            hostbuf=y_coordinates,
        )
        maximum_chunk_pixels = width * chunk_rows
        smooth_buffer = cl.Buffer(
            self.context, flags.WRITE_ONLY,
            size=maximum_chunk_pixels * np.dtype(np.float32).itemsize,
        )
        escaped_buffer = cl.Buffer(
            self.context, flags.WRITE_ONLY,
            size=maximum_chunk_pixels * np.dtype(np.uint8).itemsize,
        )

        for row_start in range(0, height, chunk_rows):
            row_end = min(height, row_start + chunk_rows)
            current_rows = row_end - row_start
            smooth = np.empty((current_rows, width), dtype=np.float32)
            escaped = np.empty((current_rows, width), dtype=np.bool_)
            self.kernel(
                self.queue,
                (width, current_rows),
                None,
                x_buffer,
                y_buffer,
                smooth_buffer,
                escaped_buffer,
                np.int32(width),
                np.int32(row_start),
                np.int32(current_rows),
                np.int32(fractal_code),
                np.int32(max_iterations),
                np.float64(julia_c_real),
                np.float64(julia_c_imag),
                np.float64(phoenix_p_real),
                np.float64(phoenix_p_imag),
            )
            cl.enqueue_copy(self.queue, smooth, smooth_buffer, is_blocking=False)
            cl.enqueue_copy(self.queue, escaped, escaped_buffer, is_blocking=False)
            self.queue.finish()
            yield row_start, row_end, smooth, escaped


    def render_final_pixels(
        self,
        x_coordinates,
        y_coordinates,
        fractal_code,
        max_iterations,
        julia_c_real,
        julia_c_imag,
        phoenix_p_real,
        phoenix_p_imag,
        depth,
        color_count,
        palette_phase,
        palette_cycles,
        custom_palette_rgb=None,
    ):
        """Render final palette-index or RGB pixels entirely on the GPU.

        Unlike iter_escape_chunks(), this transfers only the final image back
        to host memory. HSV conversion and bit-depth quantization also happen
        in the OpenCL kernel, avoiding CPU post-processing in the GUI path.
        """
        x_coordinates = np.ascontiguousarray(x_coordinates, dtype=np.float64)
        y_coordinates = np.ascontiguousarray(y_coordinates, dtype=np.float64)
        height = int(y_coordinates.size)
        width = int(x_coordinates.size)
        depth = int(depth)
        color_count = int(color_count)
        if width <= 0 or height <= 0:
            raise ValueError("OpenCL fractal dimensions must be positive.")
        if not 1 <= depth <= 24:
            raise ValueError("Fractal color depth must be between 1 and 24 bits.")

        indexed = depth <= 8
        channels = 1 if indexed else 3
        output_shape = (height, width) if indexed else (height, width, 3)
        output = np.empty(output_shape, dtype=np.uint8)
        flags = cl.mem_flags
        x_buffer = cl.Buffer(
            self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
            hostbuf=x_coordinates,
        )
        y_buffer = cl.Buffer(
            self.context, flags.READ_ONLY | flags.COPY_HOST_PTR,
            hostbuf=y_coordinates,
        )
        output_buffer = cl.Buffer(
            self.context, flags.WRITE_ONLY, size=width * height * channels
        )
        if custom_palette_rgb is None:
            custom_palette_rgb = np.asarray([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
            custom_palette_count = 0
        else:
            custom_palette_rgb = np.ascontiguousarray(custom_palette_rgb, dtype=np.uint8)
            if custom_palette_rgb.ndim != 2 or custom_palette_rgb.shape[1] != 3 or custom_palette_rgb.shape[0] < 2:
                raise ValueError("Custom GPU palette must be an RGB table with at least two entries.")
            custom_palette_count = int(custom_palette_rgb.shape[0])
        custom_palette_buffer = cl.Buffer(
            self.context, flags.READ_ONLY | flags.COPY_HOST_PTR, hostbuf=custom_palette_rgb
        )
        channel_bits = _depth_channel_bits(depth) if not indexed else (8, 8, 8)

        self.render_kernel(
            self.queue,
            (width, height),
            None,
            x_buffer,
            y_buffer,
            output_buffer,
            np.int32(width),
            np.int32(fractal_code),
            np.int32(max_iterations),
            np.float64(julia_c_real),
            np.float64(julia_c_imag),
            np.float64(phoenix_p_real),
            np.float64(phoenix_p_imag),
            np.int32(depth),
            np.int32(color_count),
            np.float32(palette_phase),
            np.float32(palette_cycles),
            custom_palette_buffer,
            np.int32(custom_palette_count),
            np.int32(channel_bits[0]),
            np.int32(channel_bits[1]),
            np.int32(channel_bits[2]),
        )
        cl.enqueue_copy(self.queue, output, output_buffer, is_blocking=False)
        self.queue.finish()
        return output


def get_opencl_renderer(device=None):
    """Return a cached renderer, defaulting to the preferred available GPU."""
    if device is None:
        devices, error = list_opencl_gpu_devices()
        if not devices:
            raise RuntimeError(error or "No OpenCL GPU is available.")
        device = devices[0]
    key = (
        str(getattr(device, "vendor", "")),
        str(getattr(device, "name", "")),
        str(getattr(device, "driver_version", "")),
    )
    with _OPENCL_RENDERER_LOCK:
        renderer = _OPENCL_RENDERER_CACHE.get(key)
        if renderer is None:
            renderer = OpenCLFractalRenderer(device)
            _OPENCL_RENDERER_CACHE[key] = renderer
        return renderer


def _render_backend_fingerprint(device):
    """Identify the CPU, GPU, and runtime versions that affect backend tuning."""
    return {
        "processor": platform.processor() or platform.uname().processor or "unknown",
        "machine": platform.machine(),
        "numba_version": str(numba.__version__),
        "numba_threads": int(numba.config.NUMBA_NUM_THREADS),
        "pyopencl_version": str(getattr(cl, "VERSION_TEXT", "unavailable")),
        "gpu_vendor": str(getattr(device, "vendor", "")),
        "gpu_name": str(getattr(device, "name", "")),
        "gpu_driver": str(getattr(device, "driver_version", "")),
        "tuning_version": OPENCL_TUNING_VERSION,
    }


def _render_resolution_tier(width, height):
    pixels = int(width) * int(height)
    if pixels <= 640 * 480:
        return "small"
    if pixels <= 1920 * 1080:
        return "medium"
    return "large"


def _backend_benchmark_dimensions(width, height):
    """Choose a representative benchmark size without making huge previews."""
    width = int(width)
    height = int(height)
    longest = max(width, height)
    if longest <= 640:
        return max(32, width), max(24, height)
    target_longest = 1024 if longest <= 1920 else 1600
    scale = target_longest / float(longest)
    return max(32, int(round(width * scale))), max(24, int(round(height * scale)))


def _benchmark_cpu_escape(
    x_coordinates, y_coordinates, fractal_code, iterations,
    julia_c_real, julia_c_imag, phoenix_p_real, phoenix_p_imag,
):
    for row_start in range(0, len(y_coordinates), 48):
        row_end = min(len(y_coordinates), row_start + 48)
        _fractal_escape_numba(
            x_coordinates, y_coordinates[row_start:row_end], fractal_code,
            iterations, julia_c_real, julia_c_imag,
            phoenix_p_real, phoenix_p_imag,
        )


def _benchmark_opencl_escape(
    renderer, x_coordinates, y_coordinates, fractal_code, iterations,
    julia_c_real, julia_c_imag, phoenix_p_real, phoenix_p_imag,
):
    for _row_start, _row_end, _smooth, _escaped in renderer.iter_escape_chunks(
        x_coordinates, y_coordinates, fractal_code, iterations,
        julia_c_real, julia_c_imag, phoenix_p_real, phoenix_p_imag,
    ):
        pass


def benchmark_fractal_backends(
    width, height, fractal_type, renderer,
    repeats=OPENCL_BENCH_REPEATS, representative=True,
):
    """Benchmark complete CPU and GPU fractal renders, including color output.

    Both paths use the same seeded randomized view and 24-bit output. The GPU
    path includes device launch, final-pixel transfer and PIL image creation;
    the CPU path includes Numba escape calculation and NumPy colorization.
    This measures the work performed by the actual GUI renderer rather than
    comparing escape kernels in isolation.
    """
    if fractal_type not in FRACTAL_CODE_BY_NAME:
        raise ValueError(f"Unknown fractal family: {fractal_type!r}")
    if representative:
        bench_width, bench_height = _backend_benchmark_dimensions(width, height)
    else:
        bench_width, bench_height = max(1, int(width)), max(1, int(height))

    iterations = OPENCL_BENCH_ITERATIONS
    repeats = max(2, int(repeats))
    seed_base = 734921

    # Warm JIT compilation and OpenCL program/kernel execution on a small view.
    for backend in ("CPU", "GPU"):
        generate_fractal_image(
            48, 32, 24,
            fractal_type=fractal_type,
            max_iterations=24,
            rng=np.random.default_rng(seed_base),
            compute_backend=backend,
            opencl_renderer=renderer if backend == "GPU" else None,
        )

    cpu_samples = []
    gpu_samples = []
    for repeat in range(repeats):
        seed = seed_base + repeat
        started = time.perf_counter()
        cpu_image, _ = generate_fractal_image(
            bench_width, bench_height, 24,
            fractal_type=fractal_type,
            max_iterations=iterations,
            rng=np.random.default_rng(seed),
            compute_backend="CPU",
        )
        cpu_samples.append(time.perf_counter() - started)
        del cpu_image

        started = time.perf_counter()
        gpu_image, _ = generate_fractal_image(
            bench_width, bench_height, 24,
            fractal_type=fractal_type,
            max_iterations=iterations,
            rng=np.random.default_rng(seed),
            compute_backend="GPU",
            opencl_renderer=renderer,
        )
        gpu_samples.append(time.perf_counter() - started)
        del gpu_image

    cpu_median = statistics.median(cpu_samples)
    gpu_median = statistics.median(gpu_samples)
    selected = "GPU" if gpu_median < cpu_median * 0.97 else "CPU"
    return {
        "selected_backend": selected,
        "cpu_median_seconds": cpu_median,
        "gpu_median_seconds": gpu_median,
        "gpu_device": opencl_device_label(renderer.device),
        "benchmark_width": bench_width,
        "benchmark_height": bench_height,
        "benchmark_scope": "complete_render_including_colorization_and_image_creation",
        "iterations": iterations,
        "repeats": repeats,
        "cpu_threads": int(numba.get_num_threads()),
        "reason": (
            "GPU was at least 3% faster for the complete rendered image."
            if selected == "GPU"
            else "CPU was faster or the complete-render difference was within the 3% safety margin."
        ),
    }


def auto_select_fractal_backend(width, height, fractal_type):
    """Choose CPU or GPU using a cached, device-specific workload benchmark."""
    thread_info = auto_optimize_numba_threads()
    devices, device_error = list_opencl_gpu_devices()
    if not devices:
        return {
            "backend": "CPU",
            "device": None,
            "cpu_threads": int(thread_info["selected_threads"]),
            "thread_info": thread_info,
            "benchmark": None,
            "reason": device_error or "No supported OpenCL GPU was found.",
            "cached": False,
        }

    try:
        renderer = get_opencl_renderer(devices[0])
    except Exception as exc:
        return {
            "backend": "CPU",
            "device": None,
            "cpu_threads": int(thread_info["selected_threads"]),
            "thread_info": thread_info,
            "benchmark": None,
            "reason": f"OpenCL initialization failed; using CPU: {exc}",
            "cached": False,
        }

    fingerprint = _render_backend_fingerprint(renderer.device)
    fingerprint["selected_cpu_threads"] = int(thread_info["selected_threads"])
    tier = _render_resolution_tier(width, height)
    key = f"{fractal_type}|{int(width)}x{int(height)}|{tier}"
    path = get_render_backend_tuning_path()

    with _RENDER_BACKEND_TUNING_LOCK:
        cached = None
        try:
            with open(path, "r", encoding="utf-8") as settings_file:
                existing_tuning = json.load(settings_file)
            if existing_tuning.get("fingerprint") == fingerprint:
                tuning = existing_tuning
                cached = tuning.get("decisions", {}).get(key)
            else:
                tuning = {"fingerprint": fingerprint, "decisions": {}}
        except (OSError, ValueError, TypeError, AttributeError):
            tuning = {"fingerprint": fingerprint, "decisions": {}}

        if isinstance(cached, dict) and cached.get("selected_backend") in ("CPU", "GPU"):
            use_gpu = cached["selected_backend"] == "GPU"
            return {
                "backend": cached["selected_backend"],
                "device": renderer.device if use_gpu else None,
                "cpu_threads": int(thread_info["selected_threads"]),
                "thread_info": thread_info,
                "benchmark": cached,
                "reason": "Loaded the saved CPU/GPU benchmark for this fractal and resolution.",
                "cached": True,
                "renderer": renderer if use_gpu else None,
            }

        try:
            benchmark = benchmark_fractal_backends(
                width, height, fractal_type, renderer
            )
        except Exception as exc:
            return {
                "backend": "CPU",
                "device": None,
                "cpu_threads": int(thread_info["selected_threads"]),
                "thread_info": thread_info,
                "benchmark": None,
                "reason": f"OpenCL benchmark failed; using CPU: {exc}",
                "cached": False,
            }

        tuning = {
            "fingerprint": fingerprint,
            "decisions": dict(tuning.get("decisions", {})),
        }
        tuning["decisions"][key] = benchmark
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_path = path + ".tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as settings_file:
                json.dump(tuning, settings_file, indent=2)
            os.replace(temporary_path, path)
        except OSError:
            pass
        finally:
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                pass

    use_gpu = benchmark["selected_backend"] == "GPU"
    return {
        "backend": benchmark["selected_backend"],
        "device": renderer.device if use_gpu else None,
        "cpu_threads": int(thread_info["selected_threads"]),
        "thread_info": thread_info,
        "benchmark": benchmark,
        "reason": benchmark["reason"],
        "cached": False,
        "renderer": renderer if use_gpu else None,
    }


def get_numba_thread_tuning_path():
    """Return the per-user cache path for automatic CPU thread tuning."""
    return os.path.join(
        os.path.dirname(get_window_position_path()), "cpu_thread_tuning.json"
    )


def _visible_numba_cpu_count():
    """Return the logical CPU count available to Numba in this process."""
    try:
        if hasattr(os, "sched_getaffinity"):
            visible = len(os.sched_getaffinity(0))
        elif hasattr(os, "process_cpu_count"):
            visible = os.process_cpu_count()
        else:
            visible = os.cpu_count()
    except (OSError, NotImplementedError):
        visible = os.cpu_count()
    visible = visible or int(numba.config.NUMBA_NUM_THREADS)
    return max(1, min(int(visible), int(numba.config.NUMBA_NUM_THREADS)))


def _numba_thread_tuning_fingerprint():
    """Identify hardware/runtime conditions that affect thread scaling."""
    processor = platform.processor() or platform.uname().processor or "unknown-cpu"
    return {
        "processor": processor,
        "machine": platform.machine(),
        "visible_logical_cpus": _visible_numba_cpu_count(),
        "numba_max_threads": int(numba.config.NUMBA_NUM_THREADS),
        "numba_version": str(numba.__version__),
        "tuning_version": NUMBA_THREAD_TUNING_VERSION,
    }


def _numba_thread_candidates(max_threads=None):
    """Return candidate thread counts, testing each count on common CPUs."""
    maximum = max_threads or _visible_numba_cpu_count()
    maximum = max(1, int(maximum))
    # Test every setting on ordinary desktop CPUs (including the 20 logical
    # threads of Intel hybrid desktop processors). On larger workstations,
    # sample a broad range and always include the machine's maximum.
    if maximum <= 24:
        return list(range(1, maximum + 1))
    candidates = {1, 2, 4, 6, 8, 10, 12, 16, 20, 24, maximum}
    candidates.update(range(28, maximum, 4))
    return sorted(value for value in candidates if 1 <= value <= maximum)


def load_numba_thread_tuning(path=None):
    """Load a compatible thread-count calibration, or return None."""
    path = path or get_numba_thread_tuning_path()
    try:
        with open(path, "r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
        selected = settings.get("selected_threads")
        if (
            settings.get("fingerprint") != _numba_thread_tuning_fingerprint()
            or isinstance(selected, bool)
            or not isinstance(selected, int)
            or not 1 <= selected <= _visible_numba_cpu_count()
        ):
            return None
        return settings
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_numba_thread_tuning(settings, path=None):
    """Save thread tuning atomically, separate from theme/window preferences."""
    path = path or get_numba_thread_tuning_path()
    selected = settings.get("selected_threads")
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise ValueError("Selected Numba thread count must be an integer.")
    if not 1 <= selected <= _visible_numba_cpu_count():
        raise ValueError("Selected Numba thread count exceeds available CPUs.")
    payload = dict(settings)
    payload["fingerprint"] = _numba_thread_tuning_fingerprint()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as settings_file:
            json.dump(payload, settings_file, indent=2)
        os.replace(temporary_path, path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def benchmark_numba_thread_counts(
    benchmark_width=NUMBA_TUNING_BENCH_WIDTH,
    benchmark_rows=NUMBA_TUNING_BENCH_ROWS,
    iterations=NUMBA_TUNING_BENCH_ITERATIONS,
    repeats=NUMBA_TUNING_BENCH_REPEATS,
):
    """Benchmark Numba thread counts on representative row-chunk workloads.

    Two formulas are measured: Julia (quadratic escape-time work) and Phoenix
    (a recurrence with additional arithmetic). A short warm-up is excluded
    from timings. The benchmark uses the production row-chunk height so the
    selected count reflects the renderer's actual parallel scheduling shape.
    """
    maximum = _visible_numba_cpu_count()
    candidates = _numba_thread_candidates(maximum)
    width = max(32, int(benchmark_width))
    rows = max(8, int(benchmark_rows))
    iterations = max(8, int(iterations))
    repeats = max(1, int(repeats))

    x_coordinates = np.linspace(-2.1, 1.2, width, dtype=np.float64)
    y_coordinates = np.linspace(-1.4, 1.4, rows, dtype=np.float64)
    # Include both a common quadratic family and a more arithmetic-heavy
    # recurrence so the chosen count is not tailored solely to one equation.
    workloads = (
        (1, -0.8, 0.156, -0.35, 0.2),
        (6, -0.8, 0.156, -0.35, 0.2),
    )

    measurements = {}
    original_threads = numba.get_num_threads()
    try:
        # Force JIT compilation and initialize Numba's thread pool before any
        # candidate is timed. Compilation time is deliberately not benchmarked.
        numba.set_num_threads(maximum)
        _fractal_escape_numba(
            x_coordinates[:32], y_coordinates[:8], 1, 8, -0.8, 0.156, -0.35, 0.2
        )

        for thread_count in candidates:
            numba.set_num_threads(thread_count)
            family_samples = {"Julia Set": [], "Phoenix": []}

            # Warm up this thread mask so the first launch cost is excluded.
            for fractal_code, jc_r, jc_i, p_r, p_i in workloads:
                _fractal_escape_numba(
                    x_coordinates, y_coordinates, fractal_code, iterations,
                    jc_r, jc_i, p_r, p_i,
                )

            for _ in range(repeats):
                for (fractal_code, jc_r, jc_i, p_r, p_i), family_name in zip(
                    workloads, ("Julia Set", "Phoenix")
                ):
                    started = time.perf_counter()
                    _fractal_escape_numba(
                        x_coordinates, y_coordinates, fractal_code, iterations,
                        jc_r, jc_i, p_r, p_i,
                    )
                    family_samples[family_name].append(time.perf_counter() - started)

            family_medians = {
                name: statistics.median(samples)
                for name, samples in family_samples.items()
            }
            # Both workload families contribute equally to the calibration.
            score = statistics.mean(family_medians.values())
            measurements[str(thread_count)] = {
                "score_seconds": score,
                "julia_median_seconds": family_medians["Julia Set"],
                "phoenix_median_seconds": family_medians["Phoenix"],
            }
    finally:
        numba.set_num_threads(original_threads)

    if not measurements:
        raise RuntimeError("Numba CPU thread calibration produced no measurements.")

    fastest_score = min(item["score_seconds"] for item in measurements.values())
    # Prefer fewer threads when performance is effectively tied (within 2%).
    near_fastest = [
        int(count)
        for count, item in measurements.items()
        if item["score_seconds"] <= fastest_score * 1.02
    ]
    selected_threads = min(near_fastest)
    return {
        "selected_threads": selected_threads,
        "measurements": measurements,
        "benchmark_width": width,
        "benchmark_rows": rows,
        "benchmark_iterations": iterations,
        "benchmark_repeats": repeats,
    }


def auto_optimize_numba_threads(
    path=None,
    force=False,
    benchmark_width=NUMBA_TUNING_BENCH_WIDTH,
    benchmark_rows=NUMBA_TUNING_BENCH_ROWS,
    iterations=NUMBA_TUNING_BENCH_ITERATIONS,
    repeats=NUMBA_TUNING_BENCH_REPEATS,
):
    """Apply a saved thread setting or benchmark and persist the best count.

    Call this from the same worker thread that will execute the fractal kernel:
    Numba's active thread mask is local to the calling Python thread.
    """
    with _NUMBA_THREAD_TUNING_LOCK:
        cached = None if force else load_numba_thread_tuning(path)
        if cached is not None:
            selected = int(cached["selected_threads"])
            numba.set_num_threads(selected)
            return {
                "selected_threads": selected,
                "cached": True,
                "benchmark_seconds": 0.0,
                "measurements": cached.get("measurements", {}),
            }

        started = time.perf_counter()
        result = benchmark_numba_thread_counts(
            benchmark_width=benchmark_width,
            benchmark_rows=benchmark_rows,
            iterations=iterations,
            repeats=repeats,
        )
        result["cached"] = False
        result["benchmark_seconds"] = time.perf_counter() - started
        try:
            save_numba_thread_tuning(result, path)
        except OSError:
            # The selected count still applies for this render if the per-user
            # config folder is read-only; the next process can tune again.
            pass
        numba.set_num_threads(result["selected_threads"])
        return result


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


# Numba compiles the per-pixel escape-time loop to native machine code.
# Rows are independent and are distributed across the CPU thread pool. cache=False
# avoids cache-path problems in PyInstaller one-file builds; compilation occurs
# once per process, then the compiled kernel is reused for every fractal render.
FRACTAL_CODE_BY_NAME = {
    "Mandelbrot": 0,
    "Julia Set": 1,
    "Burning Ship": 2,
    "Tricorn (Mandelbar)": 3,
    "Multibrot (Power 3)": 4,
    "Celtic Mandelbrot": 5,
    "Phoenix": 6,
}
NUMBA_ACCELERATION_ENABLED = True


@njit(parallel=True, nogil=True, cache=False)
def _fractal_escape_numba(
    x_coordinates,
    y_coordinates,
    fractal_code,
    max_iterations,
    julia_c_real,
    julia_c_imag,
    phoenix_p_real,
    phoenix_p_imag,
):
    """Return smoothed escape iterations and an escaped mask for every pixel."""
    height = y_coordinates.shape[0]
    width = x_coordinates.shape[0]
    smooth_iterations = np.zeros((height, width), dtype=np.float32)
    escaped = np.zeros((height, width), dtype=np.bool_)
    degree_log = math.log(3.0 if fractal_code == 4 else 2.0)

    for y in prange(height):
        ci_coordinate = y_coordinates[y]
        for x in range(width):
            cr_coordinate = x_coordinates[x]

            # Exact interior tests for the quadratic Mandelbrot set. These
            # skip points known to be inside the main cardioid or period-2 bulb.
            if fractal_code == 0:
                qx = cr_coordinate - 0.25
                q = qx * qx + ci_coordinate * ci_coordinate
                in_main_cardioid = q * (q + qx) <= 0.25 * ci_coordinate * ci_coordinate
                bx = cr_coordinate + 1.0
                in_period_two_bulb = bx * bx + ci_coordinate * ci_coordinate <= 0.0625
                if in_main_cardioid or in_period_two_bulb:
                    continue

            if fractal_code == 1:  # Julia: z0 is the pixel, c is randomized.
                zr = cr_coordinate
                zi = ci_coordinate
                cr = julia_c_real
                ci = julia_c_imag
            else:  # The remaining families use the pixel as c and z0 = 0.
                zr = 0.0
                zi = 0.0
                cr = cr_coordinate
                ci = ci_coordinate

            previous_real = 0.0
            previous_imag = 0.0

            for iteration in range(max_iterations):
                if fractal_code == 2:  # Burning Ship
                    ar = abs(zr)
                    ai = abs(zi)
                    next_real = ar * ar - ai * ai + cr
                    next_imag = 2.0 * ar * ai + ci
                elif fractal_code == 3:  # Tricorn / Mandelbar
                    next_real = zr * zr - zi * zi + cr
                    next_imag = -2.0 * zr * zi + ci
                elif fractal_code == 4:  # Multibrot power 3
                    next_real = zr * zr * zr - 3.0 * zr * zi * zi + cr
                    next_imag = 3.0 * zr * zr * zi - zi * zi * zi + ci
                elif fractal_code == 5:  # Celtic Mandelbrot
                    next_real = abs(zr * zr - zi * zi) + cr
                    next_imag = 2.0 * zr * zi + ci
                elif fractal_code == 6:  # Phoenix
                    next_real = (
                        zr * zr - zi * zi + cr
                        + phoenix_p_real * previous_real
                        - phoenix_p_imag * previous_imag
                    )
                    next_imag = (
                        2.0 * zr * zi + ci
                        + phoenix_p_real * previous_imag
                        + phoenix_p_imag * previous_real
                    )
                    previous_real = zr
                    previous_imag = zi
                else:  # Mandelbrot and Julia
                    next_real = zr * zr - zi * zi + cr
                    next_imag = 2.0 * zr * zi + ci

                magnitude_squared = next_real * next_real + next_imag * next_imag
                zr = next_real
                zi = next_imag

                if magnitude_squared > 4.0:
                    magnitude = math.sqrt(magnitude_squared)
                    smooth_value = (
                        iteration + 1.0
                        - math.log(math.log(magnitude)) / degree_log
                    )
                    if smooth_value < 0.0:
                        smooth_value = 0.0
                    elif smooth_value > max_iterations:
                        smooth_value = float(max_iterations)
                    smooth_iterations[y, x] = smooth_value
                    escaped[y, x] = True
                    break

    return smooth_iterations, escaped


def pan_fractal_view(view_state, delta_x, delta_y, display_width, display_height):
    """Return a panned copy of a fractal view after a screen-space drag."""
    if display_width <= 0 or display_height <= 0:
        raise ValueError("Preview dimensions must be positive.")
    state = dict(view_state)
    span = float(state["horizontal_span"])
    vertical_span = span * float(display_height) / float(display_width)
    state["center_real"] = float(state["center_real"]) - float(delta_x) * span / max(1.0, float(display_width) - 1.0)
    state["center_imag"] = float(state["center_imag"]) - float(delta_y) * vertical_span / max(1.0, float(display_height) - 1.0)
    return state


def zoom_fractal_view(view_state, cursor_x_ratio, cursor_y_ratio, zoom_factor,
                      image_width, image_height):
    """Zoom toward a normalized preview position while keeping that point fixed."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive.")
    if zoom_factor <= 0:
        raise ValueError("Zoom factor must be positive.")
    state = dict(view_state)
    cursor_x = min(1.0, max(0.0, float(cursor_x_ratio)))
    cursor_y = min(1.0, max(0.0, float(cursor_y_ratio)))
    old_span = float(state["horizontal_span"])
    home_span = float(state.get("home_horizontal_span", old_span))
    minimum_span = max(home_span * 1e-8, 1e-14)
    maximum_span = home_span * 50.0
    new_span = min(maximum_span, max(minimum_span, old_span / float(zoom_factor)))

    old_vertical_span = old_span * float(image_height) / float(image_width)
    new_vertical_span = new_span * float(image_height) / float(image_width)
    point_real = float(state["center_real"]) - old_span / 2.0 + cursor_x * old_span
    point_imag = float(state["center_imag"]) - old_vertical_span / 2.0 + cursor_y * old_vertical_span

    state["center_real"] = point_real - (cursor_x - 0.5) * new_span
    state["center_imag"] = point_imag - (cursor_y - 0.5) * new_vertical_span
    state["horizontal_span"] = new_span
    return state


def interpolate_fractal_view_states(start_state, end_state, progress):
    """Interpolate a viewport smoothly, using logarithmic zoom scaling."""
    progress = min(1.0, max(0.0, float(progress)))
    if progress <= 0.0:
        return dict(start_state)
    if progress >= 1.0:
        return dict(end_state)
    state = dict(start_state)
    for key in ("center_real", "center_imag"):
        state[key] = (
            float(start_state[key])
            + (float(end_state[key]) - float(start_state[key])) * progress
        )
    start_span = max(float(start_state["horizontal_span"]), 1e-300)
    end_span = max(float(end_state["horizontal_span"]), 1e-300)
    state["horizontal_span"] = math.exp(
        math.log(start_span)
        + (math.log(end_span) - math.log(start_span)) * progress
    )
    return state


def reset_fractal_view_state(view_state):
    """Return a view to the randomized starting viewport used for this fractal."""
    state = dict(view_state)
    state["center_real"] = float(state["home_center_real"])
    state["center_imag"] = float(state["home_center_imag"])
    state["horizontal_span"] = float(state["home_horizontal_span"])
    return state


def generate_fractal_image(
    width,
    height,
    depth,
    fractal_type=DEFAULT_FRACTAL_TYPE,
    max_iterations=128,
    rows_per_chunk=48,
    rng=None,
    compute_backend="CPU",
    opencl_renderer=None,
    view_state=None,
    return_view_state=False,
    custom_palette=None,
):
    """Generate a randomized or user-positioned view of a fractal family.

    Supported families are Mandelbrot, Julia Set, Burning Ship, Tricorn,
    cubic Multibrot, Celtic Mandelbrot and Phoenix. Each call randomizes its
    viewport and color cycle; Julia and Phoenix also randomize their defining
    complex parameter. Pass a NumPy Generator for repeatable test output.

    ``compute_backend`` may be CPU or GPU. CPU uses Numba; GPU uses OpenCL.
    Pass ``view_state`` to render the same viewport again after zooming or panning.
    When ``return_view_state`` is true, the function returns (image, count, state).
    Depths 1–8 use an indexed palette; depths 16 and 24 use quantized direct RGB.
    """
    width = int(width)
    height = int(height)
    depth = int(depth)
    max_iterations = int(max_iterations)
    rows_per_chunk = int(rows_per_chunk)
    fractal_type = str(fractal_type)

    if fractal_type not in FRACTAL_TYPE_OPTIONS:
        raise ValueError(
            f"Unsupported fractal type {fractal_type!r}. "
            f"Choose one of: {', '.join(FRACTAL_TYPE_OPTIONS)}."
        )
    compute_backend = str(compute_backend).upper()
    if compute_backend not in ("CPU", "GPU"):
        raise ValueError("Fractal compute backend must be CPU or GPU.")
    if compute_backend == "GPU" and opencl_renderer is None:
        opencl_renderer = get_opencl_renderer()
    if width <= 0 or height <= 0:
        raise ValueError("Fractal width and height must be positive.")
    if not 1 <= depth <= 24:
        raise ValueError("Fractal color depth must be between 1 and 24 bits.")
    if max_iterations < 8 or max_iterations > 2048:
        raise ValueError("Fractal iteration count must be between 8 and 2048.")
    if rows_per_chunk < 1:
        raise ValueError("Fractal row chunk size must be positive.")

    rng = np.random.default_rng() if rng is None else rng
    if custom_palette is None and isinstance(view_state, dict):
        custom_palette = view_state.get("palette_stops")
    custom_palette_stops = normalize_palette_stops(custom_palette) if custom_palette else None
    custom_palette_table = sample_custom_palette(custom_palette_stops, 256) if custom_palette_stops else None

    # Distinct, useful coordinate neighborhoods for each family. Repeated
    # generations select another center, zoom level and color spectrum.
    viewport_catalog = {
        "Mandelbrot": {
            "centers": [
                (-0.75, 0.10), (-0.10, 0.65), (-1.25, 0.00),
                (-0.235125, 0.827215), (-0.745, 0.186),
                (-1.25066, 0.02012), (-0.101096, 0.956286),
                (-0.77468, 0.124), (-0.1592, 1.0317),
                (-1.768, 0.001), (0.285, 0.01), (-0.512, 0.521),
            ],
            "span": 3.5,
            "zoom": (1.5, 45.0),
        },
        "Julia Set": {
            "centers": [
                (0.0, 0.0), (-0.12, 0.08), (0.18, -0.06),
                (0.0, -0.18), (-0.22, 0.14),
            ],
            "span": 3.4,
            "zoom": (0.85, 5.5),
        },
        "Burning Ship": {
            "centers": [
                (-1.74, -0.035), (-1.78, -0.045), (-1.66, -0.08),
                (-1.82, -0.12), (-1.55, -0.04), (-1.90, -0.18),
            ],
            "span": 3.7,
            "zoom": (1.0, 32.0),
        },
        "Tricorn (Mandelbar)": {
            "centers": [
                (-0.25, 0.0), (0.0, 0.0), (0.28, 0.12),
                (-0.45, 0.18), (0.15, -0.28),
            ],
            "span": 4.2,
            "zoom": (1.0, 28.0),
        },
        "Multibrot (Power 3)": {
            "centers": [
                (-0.15, 0.0), (0.15, 0.0), (-0.45, 0.2),
                (0.35, -0.18), (-0.2, 0.5),
            ],
            "span": 3.4,
            "zoom": (1.0, 24.0),
        },
        "Celtic Mandelbrot": {
            "centers": [
                (-0.2, 0.0), (-0.45, 0.15), (0.1, 0.25),
                (-0.65, -0.15), (0.25, -0.25),
            ],
            "span": 3.6,
            "zoom": (1.0, 30.0),
        },
        "Phoenix": {
            "centers": [
                (0.0, 0.0), (-0.15, 0.12), (0.2, -0.1),
                (-0.35, -0.2), (0.3, 0.28),
            ],
            "span": 3.5,
            "zoom": (0.9, 18.0),
        },
    }
    viewport = viewport_catalog[fractal_type]
    if view_state is None:
        centers = viewport["centers"]
        if rng.random() < 0.14:
            center_real = float(centers[0][0]) + float(rng.uniform(-0.12, 0.12))
            center_imag = float(centers[0][1]) + float(rng.uniform(-0.12, 0.12))
            zoom = float(rng.uniform(0.8, 1.5))
        else:
            center_index = int(rng.integers(0, len(centers)))
            center_real, center_imag = centers[center_index]
            jitter = 0.012 if fractal_type == "Mandelbrot" else 0.035
            center_real += float(rng.normal(0.0, jitter))
            center_imag += float(rng.normal(0.0, jitter))
            zoom = float(
                10.0 ** rng.uniform(
                    np.log10(viewport["zoom"][0]), np.log10(viewport["zoom"][1])
                )
            )
        horizontal_span = viewport["span"] / zoom
    else:
        view_state = dict(view_state)
        center_real = float(view_state["center_real"])
        center_imag = float(view_state["center_imag"])
        horizontal_span = float(view_state["horizontal_span"])

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

    if view_state is None:
        # Julia parameters are chosen from well-known interesting regions of
        # the parameter plane, then retained during interactive exploration.
        julia_parameters = (
            (-0.8, 0.156), (0.285, 0.01), (-0.4, 0.6), (-0.12, 0.74),
            (-0.70176, -0.3842), (0.355, 0.355), (-0.54, 0.54),
            (-0.745, 0.186),
        )
        julia_parameter = julia_parameters[int(rng.integers(0, len(julia_parameters)))]
        julia_c_real = julia_parameter[0] + float(rng.normal(0.0, 0.012))
        julia_c_imag = julia_parameter[1] + float(rng.normal(0.0, 0.012))

        # Phoenix uses z(n+1) = z(n)^2 + c + p*z(n-1).
        phoenix_parameters = ((-0.5, 0.0), (-0.35, 0.2), (-0.25, -0.3), (-0.4, 0.12))
        phoenix_parameter = phoenix_parameters[int(rng.integers(0, len(phoenix_parameters)))]
        phoenix_p_real = phoenix_parameter[0] + float(rng.normal(0.0, 0.015))
        phoenix_p_imag = phoenix_parameter[1] + float(rng.normal(0.0, 0.015))

        palette_phase = float(rng.random())
        palette_cycles = float(rng.uniform(2.2, 5.8))
        view_state_out = {
            "fractal_type": fractal_type,
            "center_real": float(center_real),
            "center_imag": float(center_imag),
            "horizontal_span": float(horizontal_span),
            "home_center_real": float(center_real),
            "home_center_imag": float(center_imag),
            "home_horizontal_span": float(horizontal_span),
            "julia_c_real": float(julia_c_real),
            "julia_c_imag": float(julia_c_imag),
            "phoenix_p_real": float(phoenix_p_real),
            "phoenix_p_imag": float(phoenix_p_imag),
            "palette_phase": float(palette_phase),
            "palette_cycles": float(palette_cycles),
            "palette_stops": list(custom_palette_stops) if custom_palette_stops else None,
        }
    else:
        if view_state.get("fractal_type", fractal_type) != fractal_type:
            raise ValueError("The saved fractal view belongs to a different fractal family.")
        julia_c_real = float(view_state["julia_c_real"])
        julia_c_imag = float(view_state["julia_c_imag"])
        phoenix_p_real = float(view_state["phoenix_p_real"])
        phoenix_p_imag = float(view_state["phoenix_p_imag"])
        palette_phase = float(view_state["palette_phase"])
        palette_cycles = float(view_state["palette_cycles"])
        view_state_out = dict(view_state)
        view_state_out.update({
            "fractal_type": fractal_type,
            "center_real": float(center_real),
            "center_imag": float(center_imag),
            "horizontal_span": float(horizontal_span),
            "palette_stops": list(custom_palette_stops) if custom_palette_stops else None,
        })


    indexed = depth <= 8
    color_count = 1 << depth
    if depth == 1:
        if custom_palette_stops:
            endpoints = sample_custom_palette(custom_palette_stops, 2)
            palette_rgb = endpoints
        else:
            palette_rgb = np.asarray([(0, 0, 0), (255, 255, 255)], dtype=np.uint8)
    elif indexed:
        palette_rgb = np.zeros((color_count, 3), dtype=np.uint8)
        if custom_palette_stops:
            palette_rgb[1:] = sample_custom_palette(custom_palette_stops, color_count - 1)
        else:
            palette_t = np.linspace(0.0, 1.0, color_count - 1, dtype=np.float32)
            palette_hue = (palette_phase + palette_t * palette_cycles) % 1.0
            palette_rgb[1:] = _hsv_to_rgb_array(palette_hue)
    else:
        palette_rgb = None

    fractal_code = FRACTAL_CODE_BY_NAME[fractal_type]
    output = (
        np.empty((height, width), dtype=np.uint8)
        if indexed
        else np.empty((height, width, 3), dtype=np.uint8)
    )

    if compute_backend == "GPU":
        # The complete OpenCL kernel writes final indexed/RGB pixels directly.
        # Only the final image bytes cross PCIe; no float escape map, boolean
        # mask, HSV conversion or bit-depth quantization runs on the CPU.
        render_arguments = (
            x_coordinates, y_coordinates, fractal_code, max_iterations,
            julia_c_real, julia_c_imag, phoenix_p_real, phoenix_p_imag,
            depth, color_count, palette_phase, palette_cycles,
        )
        if custom_palette_table is not None:
            gpu_pixels = opencl_renderer.render_final_pixels(
                *render_arguments, custom_palette_rgb=custom_palette_table
            )
        else:
            gpu_pixels = opencl_renderer.render_final_pixels(*render_arguments)
        if indexed:
            image = Image.frombytes("P", (width, height), gpu_pixels.tobytes())
            flat_palette = palette_rgb.reshape(-1).tolist()
            flat_palette.extend([0] * (768 - len(flat_palette)))
            image.putpalette(flat_palette)
        else:
            image = Image.fromarray(gpu_pixels, mode="RGB")
        if return_view_state:
            return image, color_count, view_state_out
        return image, color_count

    # CPU retains the existing row-chunked Numba kernel and NumPy color path.
    def _cpu_chunks():
        for chunk_start in range(0, height, rows_per_chunk):
            chunk_end = min(height, chunk_start + rows_per_chunk)
            smooth, escaped_mask = _fractal_escape_numba(
                x_coordinates,
                y_coordinates[chunk_start:chunk_end],
                fractal_code,
                max_iterations,
                julia_c_real,
                julia_c_imag,
                phoenix_p_real,
                phoenix_p_imag,
            )
            yield chunk_start, chunk_end, smooth, escaped_mask
    escape_chunks = _cpu_chunks()

    for row_start, row_end, smooth_iterations, escaped in escape_chunks:
        if depth == 1:
            chunk_output = escaped.astype(np.uint8)
        else:
            normalized = np.clip(
                smooth_iterations / float(max_iterations), 0.0, 1.0
            )
            if indexed:
                chunk_output = np.zeros((row_end - row_start, width), dtype=np.uint8)
                color_indices = 1 + np.minimum(
                    color_count - 2,
                    (normalized[escaped] * (color_count - 2)).astype(np.uint16),
                )
                chunk_output[escaped] = color_indices.astype(np.uint8)
            else:
                if custom_palette_table is not None:
                    palette_position = normalized * float(len(custom_palette_table) - 1)
                    lower = np.floor(palette_position).astype(np.int32)
                    upper = np.minimum(lower + 1, len(custom_palette_table) - 1)
                    blend = (palette_position - lower).astype(np.float32)[..., None]
                    chunk_output = np.rint(
                        custom_palette_table[lower].astype(np.float32) * (1.0 - blend)
                        + custom_palette_table[upper].astype(np.float32) * blend
                    ).clip(0, 255).astype(np.uint8)
                else:
                    hue = (palette_phase + normalized * palette_cycles) % 1.0
                    chunk_output = _hsv_to_rgb_array(hue)
                chunk_output[~escaped] = (0, 0, 0)
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
    else:
        image = Image.fromarray(output, mode="RGB")
    if return_view_state:
        return image, color_count, view_state_out
    return image, color_count


def generate_mandelbrot_image(
    width, height, depth, max_iterations=128, rows_per_chunk=48, rng=None
):
    """Backward-compatible wrapper for randomized Mandelbrot generation."""
    return generate_fractal_image(
        width,
        height,
        depth,
        fractal_type="Mandelbrot",
        max_iterations=max_iterations,
        rows_per_chunk=rows_per_chunk,
        rng=rng,
    )

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


def _opencl_video_batch_size(width, height):
    """Choose a batch that keeps GPU allocations bounded on 1080p and 4K."""
    bytes_per_frame = max(1, int(width) * int(height) * 3)
    target_batch_bytes = 32 * 1024 * 1024
    return max(1, min(4, target_batch_bytes // bytes_per_frame))


def _ffmpeg_video_output_filter():
    """Format frames already rotated on the GPU for broadly compatible HEVC."""
    return "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p"


_VIDEO_ENCODER_CACHE = None
_VIDEO_ENCODER_CACHE_LOCK = threading.Lock()


def normalize_video_codec(codec):
    """Normalize user-facing codec labels to the internal h264/hevc keys."""
    value = str(codec).strip().lower().replace(" ", "")
    if value in ("h264", "h.264", "avc", "h.264/avc"):
        return "h264"
    if value in ("h265", "h.265", "hevc", "h.265/hevc"):
        return "hevc"
    raise ValueError("Video codec must be H.264 or H.265/HEVC.")


def video_codec_label(codec):
    return "H.264/AVC" if normalize_video_codec(codec) == "h264" else "H.265/HEVC"


def _ffmpeg_binary_candidates():
    """Return system FFmpeg first, followed by the imageio-bundled fallback."""
    candidates = []
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        candidates.append(system_ffmpeg)
    try:
        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg:
            candidates.append(bundled_ffmpeg)
    except Exception:
        pass
    unique = []
    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized not in seen and os.path.isfile(candidate):
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _ffmpeg_encoder_listing(ffmpeg_exe):
    """Read FFmpeg's available encoder list, raising a useful error on failure."""
    result = subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=30, check=False,
        **hidden_subprocess_options(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Could not inspect FFmpeg encoders: {detail}")
    return result.stdout


def _probe_nvenc_encoder(ffmpeg_exe, encoder_name, quality_mode=False):
    """Initialize the requested NVENC rate-control mode before selecting it.

    A successful VBR probe does not guarantee that the driver's constant-QP
    path is usable. 1x1 random-pixel exports use constant QP, so probe that
    exact mode separately and choose the CPU encoder before opening the real
    frame pipe when NVENC cannot initialize it.
    """
    probe_width = 256
    probe_height = 256
    # Exercise several quality-mode frames during capability detection, not
    # just encoder initialization on a single frame. This catches rate-control
    # or GOP failures before the application's real frame pipe is opened.
    probe_frames = 8 if quality_mode else 1
    test_frame = bytes(probe_width * probe_height * 3) * probe_frames
    if quality_mode and encoder_name == "h264_nvenc":
        # Independent random frames: no temporal prediction or adaptive QP.
        # VBR-CQ is more robust than constqp on some Windows driver builds.
        encoder_args = [
            "-c:v", encoder_name, "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", str(VIDEO_QUALITY_MODE_QP), "-b:v", "0",
            "-g", "0", "-bf", "0", "-rc-lookahead", "0",
            "-spatial-aq", "0", "-temporal-aq", "0",
        ]
    elif quality_mode and encoder_name == "hevc_nvenc":
        # Match H.264's intra-only noise handling, but cap HEVC at 200 Mbit/s.
        # CQ 20 (rather than QP 12) avoids the multi-gigabit HEVC output that
        # can overwhelm common desktop players at 1080p120.
        maxrate = VIDEO_HEVC_QUALITY_MODE_MAXRATE_KBPS
        encoder_args = [
            "-c:v", encoder_name, "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", str(VIDEO_HEVC_QUALITY_MODE_CQ),
            "-b:v", f"{maxrate}k", "-maxrate", f"{maxrate}k",
            "-bufsize", f"{maxrate * 2}k",
            "-g", "0", "-bf", "0", "-rc-lookahead", "0",
            "-spatial-aq", "0", "-temporal-aq", "0",
        ]
    else:
        encoder_args = [
            "-c:v", encoder_name, "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-b:v", "1000k", "-maxrate", "1000k",
            "-bufsize", "2000k",
        ]
    command = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{probe_width}x{probe_height}", "-framerate", "30", "-i", "pipe:0",
        "-frames:v", str(probe_frames), "-an", *encoder_args,
        "-pix_fmt", "yuv420p", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            command, input=test_frame, capture_output=True, text=False,
            timeout=20, check=False, **hidden_subprocess_options(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"NVENC probe could not run: {exc}"
    if result.returncode == 0:
        return True, None
    detail = (result.stderr or result.stdout or b"").decode(
        "utf-8", errors="replace"
    ).strip()
    detail = detail[:500] if detail else ""
    return False, detail or f"NVENC probe exited with code {result.returncode}."


def _probe_hevc_nvenc(ffmpeg_exe, quality_mode=False):
    """Backward-compatible HEVC NVENC probe wrapper."""
    return _probe_nvenc_encoder(ffmpeg_exe, "hevc_nvenc", quality_mode=quality_mode)


def _probe_h264_nvenc(ffmpeg_exe, quality_mode=False):
    """Probe the NVIDIA H.264 encoder."""
    return _probe_nvenc_encoder(ffmpeg_exe, "h264_nvenc", quality_mode=quality_mode)


def select_video_encoder(codec=VIDEO_DEFAULT_CODEC, force_refresh=False, quality_mode=False):
    """Prefer NVENC for the codec and requested rate-control mode, then use CPU."""
    global _VIDEO_ENCODER_CACHE
    codec_key = normalize_video_codec(codec)
    nvenc_name = "h264_nvenc" if codec_key == "h264" else "hevc_nvenc"
    software_name = "libx264" if codec_key == "h264" else "libx265"
    pretty_codec = video_codec_label(codec)
    probe = _probe_h264_nvenc if codec_key == "h264" else _probe_hevc_nvenc
    quality_mode = bool(quality_mode)
    cache_key = (codec_key, quality_mode)

    with _VIDEO_ENCODER_CACHE_LOCK:
        if not isinstance(_VIDEO_ENCODER_CACHE, dict):
            _VIDEO_ENCODER_CACHE = {}
        if cache_key in _VIDEO_ENCODER_CACHE and not force_refresh:
            return dict(_VIDEO_ENCODER_CACHE[cache_key])

        candidates = _ffmpeg_binary_candidates()
        if not candidates:
            raise RuntimeError(
                "FFmpeg was not found. Install FFmpeg or reinstall imageio-ffmpeg."
            )

        inspected = []
        nvenc_failures = []
        listing_errors = []
        for ffmpeg_exe in candidates:
            try:
                listing = _ffmpeg_encoder_listing(ffmpeg_exe)
            except Exception as exc:
                listing_errors.append(f"{ffmpeg_exe}: {exc}")
                continue
            inspected.append((ffmpeg_exe, listing))

        for ffmpeg_exe, listing in inspected:
            if nvenc_name not in listing:
                continue
            available, reason = probe(ffmpeg_exe, quality_mode=quality_mode)
            if available:
                selected = {
                    "ffmpeg": ffmpeg_exe,
                    "encoder": nvenc_name,
                    "codec": pretty_codec,
                    "codec_key": codec_key,
                    "label": f"NVIDIA NVENC hardware encoder ({pretty_codec})",
                    "hardware": True,
                    "fallback_reason": None,
                }
                _VIDEO_ENCODER_CACHE[cache_key] = dict(selected)
                return selected
            nvenc_failures.append(f"{ffmpeg_exe}: {reason}")

        for ffmpeg_exe, listing in inspected:
            if software_name not in listing:
                continue
            reasons = nvenc_failures or (
                [f"NVENC is not included (missing {nvenc_name}) in the available FFmpeg builds."]
                if not any(nvenc_name in item[1] for item in inspected) else []
            )
            fallback_reason = "; ".join(reasons) if reasons else None
            selected = {
                "ffmpeg": ffmpeg_exe,
                "encoder": software_name,
                "codec": pretty_codec,
                "codec_key": codec_key,
                "label": f"CPU software encoder ({software_name} {pretty_codec})",
                "hardware": False,
                "fallback_reason": fallback_reason,
            }
            _VIDEO_ENCODER_CACHE[cache_key] = dict(selected)
            return selected

        details = nvenc_failures + listing_errors
        detail_text = "\n".join(details)
        raise RuntimeError(
            f"No usable {pretty_codec} encoder was found. FFmpeg needs a working "
            f"NVIDIA {nvenc_name} encoder or the CPU {software_name} encoder."
            + (f"\n\nEncoder diagnostics:\n{detail_text}" if detail_text else "")
        )


def select_hevc_encoder(force_refresh=False, quality_mode=False):
    """Backward-compatible selector for the H.265/HEVC encoder."""
    return select_video_encoder(
        "H.265/HEVC", force_refresh=force_refresh, quality_mode=quality_mode
    )


def select_h264_encoder(force_refresh=False, quality_mode=False):
    """Select the H.264/AVC NVENC encoder or its libx264 CPU fallback."""
    return select_video_encoder(
        "H.264", force_refresh=force_refresh, quality_mode=quality_mode
    )


def _hevc_quality_mode_maxrate_kbps(width=None, height=None, fps=None):
    """Return the HEVC 1x1 Quality Mode ceiling, safely scaled for tiny frames."""
    maxrate = int(VIDEO_HEVC_QUALITY_MODE_MAXRATE_KBPS)
    if width is not None and height is not None and fps is not None:
        width, height, fps = int(width), int(height), int(fps)
        if width > 0 and height > 0 and fps > 0 and width * height < 640 * 360:
            # Very small CPU x265 encodes can fail to initialize with an
            # unnecessarily huge VBV. Keep at least 500 kbit/s, then scale
            # the ceiling with pixel throughput up to the normal 200 Mbit/s.
            safe_limit = max(500, int(width * height * fps / 1000))
            maxrate = min(maxrate, safe_limit)
    return maxrate


def _video_encoder_arguments(
    encoder_info, bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS,
    width=None, height=None, fps=None, quality_mode=False,
):
    """Build either fixed-200-Mbit/s or constant-QP high-detail encoder arguments.

    Random 1x1 images contain independent high-frequency pixels in every frame.
    Bitrate-constrained VBR can change quantization substantially between frames,
    making some frames look darker or flatter. Constant-quality rate control
    keeps visual quality consistent; its bitrate can vary with frame content.
    H.264 NVENC uses VBR-CQ, while HEVC NVENC and CPU encoders use constant QP.
    """
    encoder = encoder_info["encoder"]
    codec_key = encoder_info.get("codec_key")
    if codec_key is None:
        codec_key = "h264" if encoder in ("h264_nvenc", "libx264") else "hevc"
    tag = "avc1" if codec_key == "h264" else "hvc1"
    format_args = ["-pix_fmt", "yuv420p", "-tag:v", tag]

    if quality_mode:
        qp = str(VIDEO_QUALITY_MODE_QP)
        if encoder == "h264_nvenc":
            # Each 1x1 frame is independent random noise, so inter-frame
            # prediction and adaptive quantization can introduce visible
            # frame-to-frame contrast/brightness changes. Encode intra-only,
            # with AQ and lookahead disabled, while retaining VBR-CQ to avoid
            # the long-session constqp instability seen on some NVENC builds.
            return [
                "-c:v", encoder, "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", qp, "-b:v", "0",
                "-g", "0", "-bf", "0", "-rc-lookahead", "0",
                "-spatial-aq", "0", "-temporal-aq", "0", *format_args,
            ]
        if encoder == "hevc_nvenc":
            # Intra-only VBR-CQ prevents frame-to-frame temporal decisions and
            # the 200 Mbit/s ceiling keeps 120 FPS HEVC files practical to play.
            maxrate = VIDEO_HEVC_QUALITY_MODE_MAXRATE_KBPS
            return [
                "-c:v", encoder, "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", str(VIDEO_HEVC_QUALITY_MODE_CQ),
                "-b:v", f"{maxrate}k", "-maxrate", f"{maxrate}k",
                "-bufsize", f"{maxrate * 2}k",
                "-g", "0", "-bf", "0", "-rc-lookahead", "0",
                "-spatial-aq", "0", "-temporal-aq", "0", *format_args,
            ]
        if encoder == "libx264":
            # Match the H.264 NVENC random-noise path: one independently
            # encoded I-frame per source frame, no B-frames or AQ.
            return [
                "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
                "-qp", qp, "-g", "1", "-bf", "0",
                "-x264-params", "keyint=1:min-keyint=1:scenecut=0:bframes=0:aq-mode=0",
                *format_args,
            ]
        if encoder == "libx265":
            # CPU fallback mirrors the HEVC NVENC quality strategy: all-I
            # frames, no AQ/B-frames, CRF 20 with a 200 Mbit/s VBV ceiling.
            maxrate = _hevc_quality_mode_maxrate_kbps(width, height, fps)
            params = (
                "log-level=error:pools=8:frame-threads=4:"
                "keyint=1:min-keyint=1:scenecut=0:bframes=0:aq-mode=0:"
                f"vbv-maxrate={maxrate}:vbv-bufsize={maxrate * 2}"
            )
            return [
                "-c:v", "libx265", "-preset", "ultrafast", "-threads", "0",
                "-crf", str(VIDEO_HEVC_QUALITY_MODE_CQ), "-g", "1", "-bf", "0",
                "-x265-params", params, *format_args,
            ]
        raise ValueError(f"Unsupported video encoder: {encoder!r}")

    bitrate_kbps = int(bitrate_kbps)
    if bitrate_kbps <= 0:
        raise ValueError("Video bitrate must be a positive number of kbit/s.")
    # Tiny CPU HEVC outputs need a practical VBV ceiling to initialize reliably.
    # At normal image sizes the requested fixed 200 Mbit/s target is unchanged.
    if (
        encoder == "libx265" and width is not None and height is not None
        and fps is not None and int(width) * int(height) < 640 * 360
    ):
        safe_small_frame_limit = max(500, int(int(width) * int(height) * int(fps) / 1000))
        bitrate_kbps = min(bitrate_kbps, safe_small_frame_limit)
    common_rate = [
        "-b:v", f"{bitrate_kbps}k",
        "-maxrate", f"{bitrate_kbps}k",
        "-bufsize", f"{bitrate_kbps * 2}k",
        *format_args,
    ]
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        return [
            "-c:v", encoder, "-preset", "p5", "-tune", "hq", "-rc", "vbr",
            *common_rate,
        ]
    if encoder == "libx264":
        return [
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "0",
            *common_rate,
        ]
    if encoder == "libx265":
        return [
            "-c:v", "libx265", "-preset", "ultrafast", "-threads", "0",
            "-x265-params", "log-level=error:pools=8:frame-threads=4",
            *common_rate,
        ]
    raise ValueError(f"Unsupported video encoder: {encoder!r}")


def _hevc_encoder_arguments(encoder_info, bitrate_kbps, width=None, height=None, fps=None):
    """Backward-compatible wrapper for HEVC encoder argument creation."""
    return _video_encoder_arguments(encoder_info, bitrate_kbps, width, height, fps)


def encode_random_h264_video(
    output_path,
    width,
    height,
    depth,
    duration_seconds=VIDEO_DEFAULT_SECONDS,
    fps=VIDEO_DEFAULT_FPS,
    bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS,
    pixel_size=1,
    progress_callback=None,
    bilinear=False,
    rotation_degrees=0,
    rotation_direction="Clockwise",
    compute_backend="CPU",
    video_codec=VIDEO_DEFAULT_CODEC,
    cancel_control=None,
):
    """Create an H.264 or H.265 MP4 with fresh random frames and optional OpenCL rotation."""
    width, height, depth = int(width), int(height), int(depth)
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
    quality_mode = pixel_size == 1
    if not 1 <= depth <= 24:
        raise ValueError("Color depth must be between 1 and 24 bits.")
    if width <= 0 or height <= 0 or width * height > VIDEO_MAX_PIXELS:
        raise ValueError("Video dimensions must be positive and within the 4K pixel limit.")
    if not 0 <= float(rotation_degrees) <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if str(rotation_direction) not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")

    requested_backend = str(compute_backend).strip().capitalize()
    if requested_backend not in ("Automatic", "Cpu", "Gpu"):
        raise ValueError("Video renderer must be Automatic, CPU or GPU.")
    renderer = None
    selected_backend = "CPU"
    gpu_fallback_reason = None
    if requested_backend in ("Automatic", "Gpu"):
        try:
            renderer = get_opencl_renderer()
            renderer._ensure_video_kernels()
            selected_backend = "GPU"
        except Exception as exc:
            if requested_backend == "Gpu":
                raise RuntimeError(f"GPU video export was selected, but OpenCL is unavailable: {exc}") from exc
            gpu_fallback_reason = str(exc)

    total_frames = fps * duration_seconds
    if selected_backend == "GPU":
        # Keep the palette fixed for the whole clip, just like the CPU exporter.
        palette = np.asarray(
            make_random_palette(depth) if depth <= 8 else [(0, 0, 0), (255, 255, 255)],
            dtype=np.uint8,
        )
        frame_seed = int(np.random.SeedSequence().generate_state(1, dtype=np.uint32)[0])
        filter_text = _ffmpeg_video_output_filter()
    else:
        palette = (
            np.asarray(make_random_palette(depth), dtype=np.uint8)
            if depth <= 8 else None
        )
        rng = np.random.default_rng()
        frame_seed = None
        # Random pixel art must retain its discrete source colors during
        # rotation. Bilinear rotation blends neighboring random pixels and
        # makes subsequent frames look washed out compared with frame 1.
        filter_text = build_ffmpeg_rotation_filter(
            rotation_degrees, rotation_direction, total_frames, fps,
            bilinear=False,
        )

    if cancel_control is not None:
        cancel_control.check()

    # Quality mode must be probed with its exact rate-control mode before export.
    encoder_info = select_video_encoder(video_codec, quality_mode=quality_mode)
    ffmpeg_exe = encoder_info["ffmpeg"]
    command = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps),
        "-i", "pipe:0", "-an",
        "-filter_threads", str(_ffmpeg_thread_count()), "-vf", filter_text,
        "-frames:v", str(total_frames),
        *_video_encoder_arguments(
            encoder_info, bitrate_kbps, width, height, fps, quality_mode=quality_mode
        ),
        "-r", str(fps), "-movflags", "+faststart", output_path,
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, bufsize=0, text=False,
        **hidden_subprocess_options(),
    )
    if cancel_control is not None:
        cancel_control.attach_process(process)
    try:
        if selected_backend == "GPU":
            batch_size = _opencl_video_batch_size(width, height)
            for first_frame in range(0, total_frames, batch_size):
                if cancel_control is not None:
                    cancel_control.check()
                batch_count = min(batch_size, total_frames - first_frame)
                frames = renderer.render_random_video_batch(
                    width, height, depth, pixel_size, bool(bilinear), palette,
                    frame_seed, first_frame, total_frames, float(rotation_degrees),
                    rotation_direction, batch_count,
                )
                if cancel_control is not None:
                    cancel_control.check()
                process.stdin.write(frames.tobytes())
                if progress_callback:
                    progress_callback(first_frame + batch_count)
        else:
            for frame_number in range(1, total_frames + 1):
                if cancel_control is not None:
                    cancel_control.check()
                frame_bytes = generate_pixelated_frame(
                    width, height, depth, pixel_size=pixel_size,
                    rng=rng, palette=palette, bilinear=bilinear,
                ).tobytes()
                if cancel_control is not None:
                    cancel_control.check()
                process.stdin.write(frame_bytes)
                if progress_callback and (
                    frame_number % 5 == 0 or frame_number == total_frames
                ):
                    progress_callback(frame_number)

        process.stdin.close()
        error_text = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(
                "FFmpeg failed to encode the video."
                + (f"\n\nFFmpeg details:\n{error_text}" if error_text else "")
            )
        if cancel_control is not None:
            cancel_control.check()
            cancel_control.detach_process(process)
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("FFmpeg finished, but no MP4 file was created.")
        return {
            "frames": total_frames, "backend": selected_backend,
            "device": opencl_device_label(renderer.device) if renderer else None,
            "fallback_reason": gpu_fallback_reason,
            "encoder": encoder_info["encoder"],
            "encoder_label": encoder_info["label"],
            "encoder_fallback_reason": encoder_info["fallback_reason"],
            "codec": encoder_info["codec"],
            "quality_mode": quality_mode,
            "rate_control": (
                (
                    f"NVENC VBR-CQ {VIDEO_QUALITY_MODE_QP} (intra-only)"
                    if encoder_info["encoder"] == "h264_nvenc" else
                    f"NVENC VBR-CQ {VIDEO_HEVC_QUALITY_MODE_CQ}, max {VIDEO_HEVC_QUALITY_MODE_MAXRATE_KBPS // 1000} Mbit/s (intra-only)"
                    if encoder_info["encoder"] == "hevc_nvenc" else
                    f"CPU CRF {VIDEO_HEVC_QUALITY_MODE_CQ}, max {_hevc_quality_mode_maxrate_kbps(width, height, fps) / 1000:g} Mbit/s (intra-only)"
                    if encoder_info["encoder"] == "libx265" else
                    f"Constant QP {VIDEO_QUALITY_MODE_QP}"
                ) if quality_mode else
                f"Fixed target {bitrate_kbps // 1000} Mbit/s"
            ),
        }
    except Exception as exc:
        # FFmpeg may reject an encoder/rate-control combination and exit before
        # the frame writer finishes. Preserve stderr so the user sees the real
        # cause instead of the unhelpful Windows [Errno 32] Broken pipe message.
        broken_pipe = isinstance(exc, BrokenPipeError) or (
            isinstance(exc, OSError) and getattr(exc, "errno", None) == 32
        )
        ffmpeg_return_code = process.poll()
        ffmpeg_error_text = ""
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except Exception:
            pass
        if broken_pipe:
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            ffmpeg_return_code = process.poll()
            try:
                if process.stderr and not process.stderr.closed:
                    ffmpeg_error_text = process.stderr.read().decode(
                        "utf-8", errors="replace"
                    ).strip()
            except Exception:
                pass
        for stream_name in ("stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            try:
                if stream and not stream.closed:
                    stream.close()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        _remove_incomplete_video_file(output_path)
        if cancel_control is not None:
            cancel_control.detach_process(process)
            if cancel_control.cancelled:
                raise VideoExportCancelled("Video export cancelled. Incomplete output removed.") from exc
        if broken_pipe:
            detail = ffmpeg_error_text or "FFmpeg exited without returning diagnostic text."
            raise RuntimeError(
                "FFmpeg stopped accepting video frames before export completed "
                f"(exit code {ffmpeg_return_code}).\n\nFFmpeg details:\n{detail}"
            ) from exc
        raise



def progressive_rotation_angle(frame_index, total_frames, rotation_degrees, direction):
    """Return the per-frame angle for a smooth 0-to-target video rotation."""
    total_frames = int(total_frames)
    frame_index = int(frame_index)
    rotation_degrees = float(rotation_degrees)
    direction = str(direction)
    if total_frames < 1:
        raise ValueError("A video must contain at least one frame.")
    if not 0.0 <= rotation_degrees <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if direction not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")
    progress = frame_index / max(1, total_frames - 1)
    sign = -1.0 if direction == "Clockwise" else 1.0
    # Pillow uses positive angles for counterclockwise rotation.
    return sign * rotation_degrees * min(1.0, max(0.0, progress))


def rotate_video_frame(image, frame_index, total_frames, rotation_degrees=0, direction="Clockwise"):
    """Rotate a frame smoothly around its center without changing output size."""
    angle = progressive_rotation_angle(
        frame_index, total_frames, rotation_degrees, direction
    )
    if abs(angle) < 1e-12:
        return image
    return image.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=(0, 0, 0),
    )



def build_ffmpeg_rotation_filter(
    rotation_degrees, direction, total_frames, fps, bilinear=True
):
    """Build a progressive FFmpeg rotation filter for the full video stream.

    Bilinear interpolation is the smooth default for fractal imagery. Random
    pixel exports pass bilinear=False to preserve crisp source colors.
    """
    rotation_degrees = float(rotation_degrees)
    direction = str(direction)
    total_frames = int(total_frames)
    fps = int(fps)
    if not 0.0 <= rotation_degrees <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if direction not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")
    if total_frames < 1 or fps < 1:
        raise ValueError("Frame count and frame rate must be positive.")

    filters = []
    if rotation_degrees > 0.0 and total_frames > 1:
        # FFmpeg's rotate filter uses image coordinates (positive Y points down),
        # so a positive angle is visually clockwise. This is the opposite sign
        # convention from Pillow's Image.rotate(), used by rotate_video_frame().
        sign = 1.0 if direction == "Clockwise" else -1.0
        final_radians = math.radians(rotation_degrees) * sign
        # FFmpeg's t is seconds; scale it so the final frame reaches the exact
        # selected angle (frame index / (total_frames - 1)).
        angle_expr = f"({final_radians:.15g})*t*{fps}/{total_frames - 1}"
        filters.append(
            "rotate=angle='" + angle_expr + "':ow=iw:oh=ih:"
            "fillcolor=black:bilinear=" + ("1" if bilinear else "0")
        )
    filters.extend((
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "format=yuv420p",
    ))
    return ",".join(filters)


def _ffmpeg_thread_count():
    """Return the logical CPU count for FFmpeg's threaded filters/encoder."""
    return max(1, int(os.cpu_count() or 1))

def encode_rotating_image_h264_video(
    output_path,
    source_image,
    duration_seconds=VIDEO_DEFAULT_SECONDS,
    fps=VIDEO_DEFAULT_FPS,
    bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS,
    rotation_degrees=0,
    rotation_direction="Clockwise",
    progress_callback=None,
    compute_backend="CPU",
    video_codec=VIDEO_DEFAULT_CODEC,
    cancel_control=None,
):
    """Export a still image as a rotating H.264 or H.265 MP4."""
    duration_seconds, fps = int(duration_seconds), int(fps)
    if not VIDEO_MIN_SECONDS <= duration_seconds <= VIDEO_MAX_SECONDS:
        raise ValueError("Video duration must be between 1 and 60 seconds.")
    if fps not in VIDEO_FPS_OPTIONS:
        raise ValueError("Frame rate must be 30, 60 or 120 FPS.")
    if not 0 <= float(rotation_degrees) <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if str(rotation_direction) not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")
    image = source_image.convert("RGB")
    width, height = image.size
    if width * height > VIDEO_MAX_PIXELS:
        raise ValueError("H.265 video export is limited to 8,294,400 pixels per frame.")

    requested_backend = str(compute_backend).strip().capitalize()
    if requested_backend not in ("Automatic", "Cpu", "Gpu"):
        raise ValueError("Video renderer must be Automatic, CPU or GPU.")
    renderer = None
    selected_backend = "CPU"
    gpu_fallback_reason = None
    if requested_backend in ("Automatic", "Gpu"):
        try:
            renderer = get_opencl_renderer()
            renderer._ensure_video_kernels()
            selected_backend = "GPU"
        except Exception as exc:
            if requested_backend == "Gpu":
                raise RuntimeError(f"GPU rotation was selected, but OpenCL is unavailable: {exc}") from exc
            gpu_fallback_reason = str(exc)

    total_frames = duration_seconds * fps
    if cancel_control is not None:
        cancel_control.check()
    encoder_info = select_video_encoder(video_codec)
    if selected_backend == "CPU":
        result = _encode_rotating_still_with_ffmpeg(
            output_path, image, duration_seconds, fps, bitrate_kbps,
            rotation_degrees, rotation_direction, progress_callback,
            encoder_info=encoder_info, video_codec=video_codec,
            cancel_control=cancel_control,
        )
        result["fallback_reason"] = gpu_fallback_reason
        result["encoder_fallback_reason"] = encoder_info["fallback_reason"]
        return result

    ffmpeg_exe = encoder_info["ffmpeg"]
    command = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps),
        "-i", "pipe:0", "-an", "-filter_threads", str(_ffmpeg_thread_count()),
        "-vf", _ffmpeg_video_output_filter(), "-frames:v", str(total_frames),
        *_video_encoder_arguments(encoder_info, bitrate_kbps, width, height, fps),
        "-r", str(fps), "-movflags", "+faststart", output_path,
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, bufsize=0, **hidden_subprocess_options(),
    )
    if cancel_control is not None:
        cancel_control.attach_process(process)
    try:
        source = np.asarray(image, dtype=np.uint8)
        batch_size = _opencl_video_batch_size(width, height)
        for first_frame in range(0, total_frames, batch_size):
            if cancel_control is not None:
                cancel_control.check()
            batch_count = min(batch_size, total_frames - first_frame)
            batch = np.repeat(source[np.newaxis, ...], batch_count, axis=0)
            rotated = renderer.rotate_rgb_batch(
                batch, first_frame, total_frames,
                float(rotation_degrees), rotation_direction,
            )
            if cancel_control is not None:
                cancel_control.check()
            process.stdin.write(rotated.tobytes())
            if progress_callback:
                progress_callback(first_frame + batch_count)
        process.stdin.close()
        error_text = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError("FFmpeg failed to encode the video." + (f"\n\nFFmpeg details:\n{error_text}" if error_text else ""))
        if cancel_control is not None:
            cancel_control.check()
            cancel_control.detach_process(process)
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("FFmpeg finished, but no MP4 file was created.")
        if progress_callback:
            progress_callback(total_frames)
        return {
            "frames": total_frames, "width": width, "height": height,
            "backend": selected_backend, "device": opencl_device_label(renderer.device),
            "encoder": encoder_info["encoder"], "encoder_label": encoder_info["label"],
            "encoder_fallback_reason": encoder_info["fallback_reason"],
            "codec": encoder_info["codec"],
        }
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
        _remove_incomplete_video_file(output_path)
        if cancel_control is not None:
            cancel_control.detach_process(process)
            if cancel_control.cancelled:
                raise VideoExportCancelled("Video export cancelled. Incomplete output removed.")
        raise


def _encode_rotating_still_with_ffmpeg(
    output_path, image, duration_seconds, fps, bitrate_kbps,
    rotation_degrees, rotation_direction, progress_callback=None,
    encoder_info=None, video_codec=VIDEO_DEFAULT_CODEC, cancel_control=None,
):
    """Loop a still RGB image inside FFmpeg, rotate it and encode the chosen codec."""
    width, height = image.size
    total_frames = int(duration_seconds) * int(fps)
    if cancel_control is not None:
        cancel_control.check()
    encoder_info = encoder_info or select_video_encoder(video_codec)
    ffmpeg_exe = encoder_info["ffmpeg"]
    video_filter = build_ffmpeg_rotation_filter(
        rotation_degrees, rotation_direction, total_frames, fps
    )
    with tempfile.TemporaryDirectory(prefix="pixel_generator_hevc_") as temp_dir:
        still_path = os.path.join(temp_dir, "source_frame.png")
        image.save(still_path, format="PNG", optimize=False)
        command = [
            ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            "-filter_threads", str(_ffmpeg_thread_count()),
            "-loop", "1", "-framerate", str(fps), "-i", still_path,
            "-an", "-vf", video_filter, "-frames:v", str(total_frames),
            *_video_encoder_arguments(encoder_info, bitrate_kbps, width, height, fps),
            "-r", str(fps), "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", output_path,
        ]
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            **hidden_subprocess_options(),
        )
        if cancel_control is not None:
            cancel_control.attach_process(process)
        try:
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if separator and key == "frame" and progress_callback:
                    try:
                        progress_callback(min(total_frames, int(value)))
                    except ValueError:
                        pass
            error_text = process.stderr.read()
            process.stdout.close()
            process.stderr.close()
            return_code = process.wait()
            if cancel_control is not None:
                cancel_control.check()
                cancel_control.detach_process(process)
            if return_code != 0:
                raise RuntimeError("FFmpeg failed to encode the video." + (f"\n\nFFmpeg details:\n{error_text}" if error_text else ""))
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("FFmpeg finished, but no MP4 file was created.")
            if progress_callback:
                progress_callback(total_frames)
            return {
                "frames": total_frames, "width": width, "height": height,
                "backend": "CPU", "encoder": encoder_info["encoder"],
                "encoder_label": encoder_info["label"],
                "encoder_fallback_reason": encoder_info["fallback_reason"],
                "codec": encoder_info["codec"],
            }
        except Exception:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            _remove_incomplete_video_file(output_path)
            if cancel_control is not None:
                cancel_control.detach_process(process)
                if cancel_control.cancelled:
                    raise VideoExportCancelled("Video export cancelled. Incomplete output cleanup attempted.")
            raise


def resolve_fractal_render_backend(width, height, fractal_type, rendering_mode):
    """Resolve one backend once for long-running batch/animation jobs."""
    mode = str(rendering_mode)
    if mode == "Automatic":
        info = auto_select_fractal_backend(width, height, fractal_type)
        return info["backend"], info.get("renderer"), info
    if mode == "GPU":
        renderer = get_opencl_renderer()
        return "GPU", renderer, {
            "backend": "GPU", "renderer": renderer, "device": renderer.device,
            "cpu_threads": None, "reason": "GPU rendering selected manually.",
        }
    if mode == "CPU":
        thread_info = auto_optimize_numba_threads()
        return "CPU", None, {
            "backend": "CPU", "renderer": None, "device": None,
            "cpu_threads": int(thread_info["selected_threads"]),
            "thread_info": thread_info, "reason": "CPU rendering selected manually.",
        }
    raise ValueError(f"Unsupported rendering mode: {mode!r}")


def encode_fractal_zoom_animation(
    output_path,
    width,
    height,
    depth,
    fractal_type,
    start_view_state,
    duration_seconds=ANIMATION_DEFAULT_SECONDS,
    fps=ANIMATION_DEFAULT_FPS,
    zoom_factor=25.0,
    target_x=0.5,
    target_y=0.5,
    pixel_size=1,
    bilinear=False,
    rendering_mode=DEFAULT_RENDERING_MODE,
    progress_callback=None,
    bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS,
    rotation_degrees=0,
    rotation_direction="Clockwise",
    video_codec=VIDEO_DEFAULT_CODEC,
    cancel_control=None,
):
    """Render an H.264 or H.265 zoom journey through the current fractal viewport."""
    width, height, depth = int(width), int(height), int(depth)
    duration_seconds, fps = int(duration_seconds), int(fps)
    if not VIDEO_MIN_SECONDS <= duration_seconds <= VIDEO_MAX_SECONDS:
        raise ValueError("Animation duration must be between 1 and 60 seconds.")
    if fps not in VIDEO_FPS_OPTIONS:
        raise ValueError("Animation frame rate must be 30, 60 or 120 FPS.")
    if width * height > VIDEO_MAX_PIXELS:
        raise ValueError("Fractal animation video is limited to 8,294,400 pixels per frame (4K).")
    if not isinstance(start_view_state, dict):
        raise ValueError("Generate or load a fractal before creating an animation.")
    if not 1.0 < float(zoom_factor) <= 10000.0:
        raise ValueError("Zoom factor must be greater than 1 and no more than 10,000.")
    if not 1 <= int(pixel_size) <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    if not 0 <= float(rotation_degrees) <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if str(rotation_direction) not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")
    if cancel_control is not None:
        cancel_control.check()

    backend, renderer, render_info = resolve_fractal_render_backend(
        width, height, fractal_type, rendering_mode
    )
    if backend == "GPU":
        try:
            renderer._ensure_video_kernels()
        except Exception:
            if str(rendering_mode) != "Automatic":
                raise
            backend, renderer, render_info = resolve_fractal_render_backend(
                width, height, fractal_type, "CPU"
            )
    start_state = dict(start_view_state)
    end_state = zoom_fractal_view(
        start_state, float(target_x), float(target_y), float(zoom_factor), width, height
    )
    total_frames = duration_seconds * fps
    if cancel_control is not None:
        cancel_control.check()
    encoder_info = select_video_encoder(video_codec)
    ffmpeg_exe = encoder_info["ffmpeg"]

    gpu_rotation = backend == "GPU"
    video_filter = (
        _ffmpeg_video_output_filter() if gpu_rotation else
        build_ffmpeg_rotation_filter(rotation_degrees, rotation_direction, total_frames, fps)
    )
    command = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-filter_threads", str(_ffmpeg_thread_count()),
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps),
        "-i", "pipe:0", "-an", "-vf", video_filter,
        "-frames:v", str(total_frames),
        *_video_encoder_arguments(encoder_info, bitrate_kbps, width, height, fps),
        "-r", str(fps), "-movflags", "+faststart", output_path,
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, bufsize=0, **hidden_subprocess_options(),
    )
    if cancel_control is not None:
        cancel_control.attach_process(process)
    try:
        for frame_number in range(total_frames):
            if cancel_control is not None:
                cancel_control.check()
            progress = frame_number / max(1, total_frames - 1)
            frame_state = interpolate_fractal_view_states(start_state, end_state, progress)
            image, _count = generate_fractal_image(
                width, height, depth, fractal_type=fractal_type,
                compute_backend=backend, opencl_renderer=renderer,
                view_state=frame_state,
            )
            frame = pixelate_image(image, pixel_size, bilinear=bilinear).convert("RGB")
            if gpu_rotation:
                rotated = renderer.rotate_rgb_batch(
                    np.asarray(frame, dtype=np.uint8)[np.newaxis, ...],
                    frame_number, total_frames, rotation_degrees, rotation_direction,
                )[0]
                if cancel_control is not None:
                    cancel_control.check()
                process.stdin.write(rotated.tobytes())
            else:
                # FFmpeg performs rotation in its threaded filter graph on the CPU path.
                if cancel_control is not None:
                    cancel_control.check()
                process.stdin.write(frame.tobytes())
            if progress_callback and ((frame_number + 1) % 2 == 0 or frame_number + 1 == total_frames):
                progress_callback(frame_number + 1)
        process.stdin.close()
        error_text = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError("FFmpeg failed to encode the fractal animation." + (f"\n\nFFmpeg details:\n{error_text}" if error_text else ""))
        if cancel_control is not None:
            cancel_control.check()
            cancel_control.detach_process(process)
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("FFmpeg finished, but no animation MP4 was created.")
        return {
            "backend": backend, "device": render_info.get("device"),
            "frames": total_frames, "encoder": encoder_info["encoder"],
            "encoder_label": encoder_info["label"],
            "encoder_fallback_reason": encoder_info["fallback_reason"],
            "codec": encoder_info["codec"],
        }
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
        _remove_incomplete_video_file(output_path)
        if cancel_control is not None:
            cancel_control.detach_process(process)
            if cancel_control.cancelled:
                raise VideoExportCancelled("Fractal animation cancelled. Incomplete output removed.")
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



def encode_fractal_zoom_animation_gif(
    output_path,
    width,
    height,
    depth,
    fractal_type,
    start_view_state,
    duration_seconds=GIF_DEFAULT_SECONDS,
    zoom_factor=25.0,
    target_x=0.5,
    target_y=0.5,
    pixel_size=1,
    bilinear=False,
    rendering_mode=DEFAULT_RENDERING_MODE,
    progress_callback=None,
    rotation_degrees=0,
    rotation_direction="Clockwise",
    resolution=GIF_DEFAULT_RESOLUTION,
    cancel_control=None,
):
    """Render a 30-FPS fractal zoom/rotation journey as an animated GIF.

    The GIF resolution must be one of the same 13 presets offered by the main
    random-pixel GIF exporter. A small set of representative animation frames
    builds one shared global palette; the complete animation is then rendered
    and quantized against that palette so colors remain stable throughout.
    """
    width, height, depth = int(width), int(height), int(depth)
    duration_seconds = int(duration_seconds)
    gif_width, gif_height = normalize_gif_resolution(resolution)
    pixel_size = int(pixel_size)

    if not GIF_MIN_SECONDS <= duration_seconds <= GIF_MAX_SECONDS:
        raise ValueError(
            f"GIF duration must be between {GIF_MIN_SECONDS} and {GIF_MAX_SECONDS} seconds."
        )
    if not 1 <= depth <= 24:
        raise ValueError("Fractal color depth must be between 1 and 24 bits.")
    if not 1 <= pixel_size <= 32:
        raise ValueError("Pixel size must be between 1x1 and 32x32.")
    if not isinstance(start_view_state, dict):
        raise ValueError("Generate or load a fractal before exporting an animated GIF.")
    if not 1.0 < float(zoom_factor) <= 10000.0:
        raise ValueError("Zoom factor must be greater than 1 and no more than 10,000.")
    if not (0.0 <= float(target_x) <= 1.0 and 0.0 <= float(target_y) <= 1.0):
        raise ValueError("GIF zoom target coordinates must be between 0 and 1.")
    if not 0 <= float(rotation_degrees) <= VIDEO_MAX_ROTATION_DEGREES:
        raise ValueError("Rotation angle must be between 0 and 720 degrees.")
    if str(rotation_direction) not in ("Clockwise", "Counterclockwise"):
        raise ValueError("Rotation direction must be Clockwise or Counterclockwise.")
    if cancel_control is not None:
        cancel_control.check()

    backend, renderer, render_info = resolve_fractal_render_backend(
        gif_width, gif_height, fractal_type, rendering_mode
    )
    start_state = dict(start_view_state)
    end_state = zoom_fractal_view(
        start_state, float(target_x), float(target_y), float(zoom_factor),
        gif_width, gif_height,
    )
    total_frames = duration_seconds * GIF_FPS
    total_duration_ms = duration_seconds * 1000

    def render_frame(frame_index, render_width, render_height, render_pixel_size):
        if cancel_control is not None:
            cancel_control.check()
        progress = frame_index / max(1, total_frames - 1)
        frame_state = interpolate_fractal_view_states(
            start_state, end_state, progress
        )
        image, _color_count = generate_fractal_image(
            render_width,
            render_height,
            depth,
            fractal_type=fractal_type,
            compute_backend=backend,
            opencl_renderer=renderer,
            view_state=frame_state,
        )
        if cancel_control is not None:
            cancel_control.check()
        frame = pixelate_image(
            image, render_pixel_size, bilinear=bilinear
        ).convert("RGB")
        frame = rotate_video_frame(
            frame,
            frame_index,
            total_frames,
            rotation_degrees=rotation_degrees,
            direction=rotation_direction,
        )
        return frame

    # Build a representative palette from evenly spaced moments in the zoom.
    # The sample render is capped at 160x120 to keep palette preparation cheap,
    # while retaining the selected GIF aspect ratio and approximate pixel size.
    sample_scale = min(1.0, 160.0 / gif_width, 120.0 / gif_height)
    sample_width = max(1, int(round(gif_width * sample_scale)))
    sample_height = max(1, int(round(gif_height * sample_scale)))
    sample_pixel_size = max(1, int(round(pixel_size * sample_scale)))
    sample_count = min(8, total_frames)
    if sample_count == 1:
        sample_indices = [0]
    else:
        sample_indices = sorted({
            int(round(index * (total_frames - 1) / (sample_count - 1)))
            for index in range(sample_count)
        })

    palette_samples = Image.new(
        "RGB", (sample_width, sample_height * len(sample_indices))
    )
    frames = []
    try:
        for sample_number, frame_index in enumerate(sample_indices):
            if cancel_control is not None:
                cancel_control.check()
            sample_frame = render_frame(
                frame_index, sample_width, sample_height, sample_pixel_size
            )
            palette_samples.paste(
                sample_frame, (0, sample_number * sample_height)
            )

        shared_palette = palette_samples.quantize(
            colors=256,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        del palette_samples

        for frame_index in range(total_frames):
            if cancel_control is not None:
                cancel_control.check()
            rgb_frame = render_frame(
                frame_index, gif_width, gif_height, pixel_size
            )
            indexed_frame = rgb_frame.quantize(
                palette=shared_palette,
                dither=Image.Dither.NONE,
            )
            frames.append(indexed_frame)
            if progress_callback:
                progress_callback(frame_index + 1)

        if cancel_control is not None:
            cancel_control.check()
        durations = gif_frame_durations_ms(total_frames, total_duration_ms)
        _write_gif_frames_preserving_duplicates(output_path, frames, durations)
        if cancel_control is not None:
            cancel_control.check()

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Fractal GIF encoding finished, but no file was created.")
        with Image.open(output_path) as check:
            if check.format != "GIF":
                raise RuntimeError("Fractal animation output is not a valid GIF file.")
            if check.size != (gif_width, gif_height):
                raise RuntimeError(
                    f"GIF encoder produced {check.size}; expected {(gif_width, gif_height)}."
                )
            if getattr(check, "n_frames", 1) != total_frames:
                raise RuntimeError(
                    f"GIF encoder produced {getattr(check, 'n_frames', 1)} frames; "
                    f"expected {total_frames}."
                )
            actual_duration = 0
            for frame_index in range(check.n_frames):
                check.seek(frame_index)
                actual_duration += int(check.info.get("duration", 0))
            if actual_duration != total_duration_ms:
                raise RuntimeError(
                    f"GIF duration mismatch: expected {total_duration_ms} ms, "
                    f"got {actual_duration} ms."
                )

        return {
            "format": "GIF",
            "backend": backend,
            "device": render_info.get("device"),
            "frames": total_frames,
            "width": gif_width,
            "height": gif_height,
            "duration_seconds": duration_seconds,
            "fps": GIF_FPS,
        }
    except Exception:
        _remove_incomplete_video_file(output_path)
        if cancel_control is not None and cancel_control.cancelled:
            raise VideoExportCancelled(
                "Fractal GIF export cancelled. Incomplete GIF removed."
            )
        raise


class RandomPixelGenerator:
    """Random-pixel image, fractal, H.265 video and GIF generator."""

    def __init__(self, root):
        self.root = root
        self.root.title("Random Pixel Image & Video Generator")
        self.window_position_path = get_window_position_path()
        self.saved_window_position = load_window_position(self.window_position_path)
        self.theme_preference_path = get_theme_preference_path()
        self.current_theme = load_theme_preference(self.theme_preference_path)
        self.theme_var = tk.StringVar(value=self.current_theme)
        self.rendering_mode_preference_path = get_rendering_mode_preference_path()
        self.rendering_mode_var = tk.StringVar(
            value=load_rendering_mode_preference(self.rendering_mode_preference_path)
        )
        self.bookmarks_path = get_fractal_bookmarks_path()
        self.bookmarks = load_fractal_bookmarks(self.bookmarks_path)
        self.custom_palettes_path = get_custom_palettes_path()
        self.custom_palettes = load_custom_palettes(self.custom_palettes_path)
        self.active_palette_name = load_active_palette()
        self.active_palette_stops = self.custom_palettes.get(self.active_palette_name)
        if self.active_palette_name != "Random" and self.active_palette_stops is None:
            self.active_palette_name = "Random"
            save_active_palette("Random")
        self.gallery_auto_save_var = tk.BooleanVar(value=load_gallery_auto_save())
        self.fractal_history = []
        self.fractal_history_index = -1
        self.is_batch_generating = False
        self.is_exporting_animation = False
        self.active_video_export_control = None
        self.batch_cancel_event = threading.Event()
        self.batch_queue = queue.Queue()
        self.animation_queue = queue.Queue()
        self.batch_window = None
        self.batch_progress = None
        self.batch_status_label = None
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
        self.current_fractal_type = DEFAULT_FRACTAL_TYPE
        self.current_fractal_view_state = None
        self.current_numba_threads = None
        self.current_render_backend = None
        self.current_render_device = None
        self.current_render_seconds = None
        self.current_backend_setup_seconds = None
        self.current_render_reason = None
        # Disable navigation actions until the first fractal has been generated.
        self._update_navigation_menu_state()

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
        self.fractal_type_var = tk.StringVar(value=DEFAULT_FRACTAL_TYPE)
        self.bilinear_var = tk.BooleanVar(value=False)
        self.pixel_size_var = tk.IntVar(value=1)
        self.pixel_size_label_var = tk.StringVar(value="1×1")
        self.fps_index_var = tk.IntVar(value=1)  # 0=30, 1=60, 2=120 FPS
        self.fps_label_var = tk.StringVar(value=f"{VIDEO_DEFAULT_FPS} FPS")
        self.duration_var = tk.IntVar(value=VIDEO_DEFAULT_SECONDS)
        self.video_codec_var = tk.StringVar(value=VIDEO_DEFAULT_CODEC)
        self.current_video_codec = VIDEO_DEFAULT_CODEC
        self.current_video_bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
        self.duration_label_var = tk.StringVar(
            value=f"{VIDEO_DEFAULT_SECONDS} seconds"
        )
        self.rotation_degrees_var = tk.IntVar(value=0)
        self.rotation_degrees_label_var = tk.StringVar(value="0°")
        self.rotation_direction_var = tk.StringVar(value="Clockwise")
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

        ttk.Label(depth_frame, text="Fractal type:").pack(side="left", padx=(8, 4))
        self.fractal_type_combo = ttk.Combobox(
            depth_frame,
            textvariable=self.fractal_type_var,
            values=FRACTAL_TYPE_OPTIONS,
            width=22,
            state="readonly",
        )
        self.fractal_type_combo.pack(side="left", padx=(0, 6))
        self.fractal_type_combo.bind(
            "<<ComboboxSelected>>", self._on_fractal_type_change
        )
        self.reset_view_button = ttk.Button(
            depth_frame,
            text="Reset View",
            command=self.reset_fractal_view,
            state="disabled",
        )
        self.reset_view_button.pack(side="left", padx=(2, 6))

        ttk.Label(depth_frame, text="Renderer:").pack(side="left", padx=(8, 4))
        self.rendering_mode_combo = ttk.Combobox(
            depth_frame,
            textvariable=self.rendering_mode_var,
            values=RENDERING_MODE_OPTIONS,
            width=10,
            state="readonly",
        )
        self.rendering_mode_combo.pack(side="left", padx=(0, 6))
        self.rendering_mode_combo.bind(
            "<<ComboboxSelected>>", self._on_rendering_mode_change
        )

        self.save_button = ttk.Button(
            depth_frame, text="Save PNG...", command=self.save_image, state="disabled"
        )
        self.save_button.pack(side="left", padx=6)

        self.video_button = ttk.Button(
            depth_frame, text="Export Video...", command=self.export_video
        )
        self.video_button.pack(side="left", padx=6)
        self.cancel_video_button = ttk.Button(
            depth_frame, text="Cancel Export", command=self.cancel_video_export,
            state="disabled",
        )

        self.gif_button = ttk.Button(
            depth_frame, text="Export GIF...", command=self.export_gif
        )
        self.gif_button.pack(side="left", padx=6)
        self.cancel_video_button.pack_forget()

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

        rotation_frame = ttk.Frame(video_controls_frame)
        rotation_frame.grid(row=1, column=0, padx=(0, 18), pady=(8, 0), sticky="nw")
        ttk.Label(rotation_frame, text="H.265 image rotation:").grid(
            row=0, column=0, sticky="w"
        )
        self.rotation_scale = tk.Scale(
            rotation_frame,
            variable=self.rotation_degrees_var,
            from_=0,
            to=VIDEO_MAX_ROTATION_DEGREES,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=330,
            width=15,
            sliderlength=18,
            highlightthickness=0,
            borderwidth=0,
            command=self._on_rotation_change,
        )
        self.rotation_scale.grid(row=1, column=0, sticky="w")
        ttk.Label(rotation_frame, text="0°").grid(row=2, column=0, sticky="w")
        ttk.Label(rotation_frame, textvariable=self.rotation_degrees_label_var).grid(
            row=2, column=0
        )
        ttk.Label(rotation_frame, text="720°").grid(row=2, column=0, sticky="e")
        direction_frame = ttk.Frame(video_controls_frame)
        direction_frame.grid(row=1, column=1, padx=(0, 0), pady=(8, 0), sticky="nw")
        ttk.Label(direction_frame, text="Rotation direction:").grid(
            row=0, column=0, sticky="w"
        )
        self.rotation_direction_combo = ttk.Combobox(
            direction_frame,
            textvariable=self.rotation_direction_var,
            values=["Clockwise", "Counterclockwise"],
            width=17,
            state="readonly",
        )
        self.rotation_direction_combo.grid(row=1, column=0, sticky="w")

        encoding_frame = ttk.Frame(video_controls_frame)
        encoding_frame.grid(row=2, column=0, columnspan=4, padx=(0, 0), pady=(8, 0), sticky="nw")
        ttk.Label(encoding_frame, text="Video codec:").pack(side="left", padx=(0, 5))
        self.video_codec_combo = ttk.Combobox(
            encoding_frame, textvariable=self.video_codec_var,
            values=VIDEO_CODEC_OPTIONS, width=14, state="readonly",
        )
        self.video_codec_combo.pack(side="left", padx=(0, 18))
        ttk.Label(
            encoding_frame,
            text="Random 1×1: constant-quality mode (bitrate varies)  |  Other exports: 200 Mbit/s",
        ).pack(side="left")

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
        self.canvas.bind("<ButtonPress-1>", self._on_fractal_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_fractal_pan_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_fractal_pan_end)
        self.canvas.bind("<MouseWheel>", self._on_fractal_mousewheel)
        self.canvas.bind("<Button-4>", self._on_fractal_mousewheel_linux)
        self.canvas.bind("<Button-5>", self._on_fractal_mousewheel_linux)
        self.preview_bounds = None
        self._pan_drag = None

        # ttk widgets are themed by ttkbootstrap; apply matching colors to the
        # remaining classic Tk scales, canvas, menus and About hyperlink.
        self._apply_classic_widget_theme()

        self.root.update_idletasks()
        self.resize_window_to_image(*DEFAULT_IMAGE_RESOLUTION)
        self.generate_image()

        self.root.after(60, self._poll_image_result)
        self.root.after(80, self._poll_video_result)
        self.root.after(80, self._poll_gif_result)
        self.root.after(100, self._poll_batch_result)
        self.root.after(100, self._poll_animation_result)

    def _create_menu(self):
        """Create Fractal Tools, Themes and About menus at the right end."""
        self.menu_bar = ttk.Frame(self.root, padding=(8, 2, 12, 2))
        self.menu_bar.pack(fill="x")

        self.fractal_tools_menu = tk.Menu(self.root, tearoff=0)
        self.fractal_tools_menu.add_command(
            label="Save Current View as Bookmark...", command=self.save_current_bookmark
        )
        self.fractal_tools_menu.add_command(
            label="Manage Fractal Bookmarks...", command=self.manage_bookmarks_dialog
        )
        self.fractal_tools_menu.add_separator()
        self.fractal_tools_menu.add_command(
            label="Undo Navigation     Ctrl+Z", command=self.undo_fractal_navigation
        )
        self.fractal_tools_menu.add_command(
            label="Redo Navigation     Ctrl+Y", command=self.redo_fractal_navigation
        )
        self.fractal_tools_menu.add_separator()
        self.fractal_tools_menu.add_command(
            label="Open Fractal Gallery...", command=self.open_fractal_gallery
        )
        self.fractal_tools_menu.add_checkbutton(
            label="Automatically Save New Fractals to Gallery",
            variable=self.gallery_auto_save_var,
            command=self._save_gallery_auto_save_preference,
        )
        self.fractal_tools_menu.add_command(
            label="Edit Color Palettes...", command=self.open_palette_editor
        )
        self.fractal_tools_menu.add_separator()
        self.fractal_tools_menu.add_command(
            label="Batch Generate 100 / 1,000 Fractals...",
            command=self.open_batch_generation_dialog,
        )
        self.fractal_tools_menu.add_command(
            label="Fractal Animation Studio...",
            command=self.open_fractal_animation_studio,
        )

        self.themes_menu = tk.Menu(self.root, tearoff=0)
        self._native_theme_menus = [self.fractal_tools_menu, self.themes_menu]
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

        self.fractal_tools_menu_button = ttk.Menubutton(
            self.menu_bar, text="Fractal Tools", menu=self.fractal_tools_menu
        )
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
        # Keep Themes directly beside About, with Fractal Tools to their left.
        self.about_menu_button.pack(side="right")
        self.themes_menu_button.pack(side="right", padx=(0, 8))
        self.fractal_tools_menu_button.pack(side="right", padx=(0, 8))
        self.root.bind("<Control-z>", lambda _event: self.undo_fractal_navigation())
        self.root.bind("<Control-y>", lambda _event: self.redo_fractal_navigation())
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
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
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
            self._render_fractal_view(self.current_fractal_view_state)
        else:
            self.generate_image()

    def _render_fractal_view(self, view_state):
        """Re-render the current fractal using the supplied saved viewport."""
        if self.current_image_type != "fractal" or not isinstance(view_state, dict):
            return
        self._start_image_generation(
            "fractal",
            fractal_type=str(view_state.get("fractal_type", self.current_fractal_type)),
            fractal_view_state=dict(view_state),
        )

    def _commit_fractal_view(self, view_state, render=True):
        """Append a user navigation/palette change to the undo history."""
        if not isinstance(view_state, dict):
            return
        state = dict(view_state)
        if self.fractal_history_index >= 0:
            self.fractal_history = self.fractal_history[:self.fractal_history_index + 1]
        self.fractal_history.append(state)
        if len(self.fractal_history) > MAX_FRACTAL_HISTORY:
            self.fractal_history = self.fractal_history[-MAX_FRACTAL_HISTORY:]
        self.fractal_history_index = len(self.fractal_history) - 1
        self.current_fractal_view_state = state
        if render:
            self._render_fractal_view(state)
        self._update_navigation_menu_state()

    def _reset_fractal_history(self, view_state):
        self.fractal_history = [dict(view_state)] if isinstance(view_state, dict) else []
        self.fractal_history_index = 0 if self.fractal_history else -1
        self.current_fractal_view_state = dict(view_state) if isinstance(view_state, dict) else None
        self._update_navigation_menu_state()

    def _update_navigation_menu_state(self):
        menu = getattr(self, "fractal_tools_menu", None)
        if menu is None:
            return
        try:
            has_fractal = (
                getattr(self, "current_image_type", None) == "fractal"
                and isinstance(getattr(self, "current_fractal_view_state", None), dict)
            )
            undo_enabled = has_fractal and self.fractal_history_index > 0
            redo_enabled = has_fractal and 0 <= self.fractal_history_index < len(self.fractal_history) - 1
            # Menu order: bookmark, manager, separator, undo, redo.
            menu.entryconfigure(0, state="normal" if has_fractal else "disabled")
            menu.entryconfigure(3, state="normal" if undo_enabled else "disabled")
            menu.entryconfigure(4, state="normal" if redo_enabled else "disabled")
        except tk.TclError:
            pass

    def undo_fractal_navigation(self):
        if (self.current_image_type != "fractal" or self.is_generating
                or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return
        if self.fractal_history_index > 0:
            self.fractal_history_index -= 1
            state = dict(self.fractal_history[self.fractal_history_index])
            self.current_fractal_type = state.get("fractal_type", self.current_fractal_type)
            self.fractal_type_var.set(self.current_fractal_type)
            self.current_image_type = "fractal"
            self.current_fractal_view_state = state
            self._render_fractal_view(state)
            self._update_navigation_menu_state()

    def redo_fractal_navigation(self):
        if (self.current_image_type != "fractal" or self.is_generating
                or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return
        if self.fractal_history_index < len(self.fractal_history) - 1:
            self.fractal_history_index += 1
            state = dict(self.fractal_history[self.fractal_history_index])
            self.current_fractal_type = state.get("fractal_type", self.current_fractal_type)
            self.fractal_type_var.set(self.current_fractal_type)
            self.current_image_type = "fractal"
            self.current_fractal_view_state = state
            self._render_fractal_view(state)
            self._update_navigation_menu_state()

    def reset_fractal_view(self):
        """Return to the randomized starting view for the current fractal."""
        if (
            self.current_image_type != "fractal"
            or not isinstance(self.current_fractal_view_state, dict)
            or self.is_generating
            or self.is_exporting_video
            or self.is_exporting_gif
            or self.is_batch_generating
            or self.is_exporting_animation
        ):
            return
        self._commit_fractal_view(reset_fractal_view_state(self.current_fractal_view_state))

    def _preview_coordinates(self, x, y):
        """Convert canvas coordinates to normalized image coordinates."""
        bounds = self.preview_bounds
        if not bounds:
            return None
        left, top, width, height = bounds
        if x < left or y < top or x > left + width - 1 or y > top + height - 1:
            return None
        return (
            min(1.0, max(0.0, (float(x) - left) / max(1, width - 1))),
            min(1.0, max(0.0, (float(y) - top) / max(1, height - 1))),
        )

    def _on_fractal_pan_start(self, event):
        if (
            self.current_image_type != "fractal"
            or not isinstance(self.current_fractal_view_state, dict)
            or self.is_generating
            or self.is_exporting_video
            or self.is_exporting_gif
            or self.is_batch_generating
            or self.is_exporting_animation
        ):
            return
        if self._preview_coordinates(event.x, event.y) is None:
            return
        self._pan_drag = {
            "start_x": int(event.x),
            "start_y": int(event.y),
            "last_x": int(event.x),
            "last_y": int(event.y),
            "view_state": dict(self.current_fractal_view_state),
            "bounds": tuple(self.preview_bounds),
        }
        try:
            self.canvas.configure(cursor="fleur")
        except tk.TclError:
            pass

    def _on_fractal_pan_motion(self, event):
        if self._pan_drag is None:
            return
        delta_x = int(event.x) - self._pan_drag["last_x"]
        delta_y = int(event.y) - self._pan_drag["last_y"]
        if delta_x or delta_y:
            self.canvas.move("preview_image", delta_x, delta_y)
            self._pan_drag["last_x"] = int(event.x)
            self._pan_drag["last_y"] = int(event.y)
            self.status_var.set("Panning fractal — release the mouse to render this area...")

    def _on_fractal_pan_end(self, event):
        if self._pan_drag is None:
            return
        drag = self._pan_drag
        self._pan_drag = None
        try:
            self.canvas.configure(cursor="")
        except tk.TclError:
            pass
        delta_x = int(event.x) - drag["start_x"]
        delta_y = int(event.y) - drag["start_y"]
        if abs(delta_x) + abs(delta_y) < 3:
            self.show_preview()
            return
        _left, _top, display_width, display_height = drag["bounds"]
        view_state = pan_fractal_view(
            drag["view_state"], delta_x, delta_y,
            display_width, display_height,
        )
        self._commit_fractal_view(view_state)

    def _zoom_fractal_at(self, x, y, zoom_factor):
        if (
            self.current_image_type != "fractal"
            or not isinstance(self.current_fractal_view_state, dict)
            or self.is_generating
            or self.is_exporting_video
            or self.is_exporting_gif
            or self.is_batch_generating
            or self.is_exporting_animation
        ):
            return "break"
        ratios = self._preview_coordinates(x, y)
        if ratios is None:
            return "break"
        _left, _top, display_width, display_height = self.preview_bounds
        if self.base_image is None:
            return "break"
        view_state = zoom_fractal_view(
            self.current_fractal_view_state,
            ratios[0], ratios[1], zoom_factor,
            self.base_image.width, self.base_image.height,
        )
        if view_state["horizontal_span"] != self.current_fractal_view_state["horizontal_span"]:
            self._commit_fractal_view(view_state)
        return "break"

    def _on_fractal_mousewheel(self, event):
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return "break"
        steps = max(0.25, min(4.0, abs(delta) / 120.0))
        zoom_factor = 1.25 ** steps if delta > 0 else 1.0 / (1.25 ** steps)
        return self._zoom_fractal_at(event.x, event.y, zoom_factor)

    def _on_fractal_mousewheel_linux(self, event):
        zoom_factor = 1.25 if int(getattr(event, "num", 0)) == 4 else 1.0 / 1.25
        return self._zoom_fractal_at(event.x, event.y, zoom_factor)

    def _on_fractal_type_change(self, _event=None):
        """Regenerate immediately when switching type while a fractal is shown."""
        selected = self.fractal_type_var.get()
        if selected not in FRACTAL_TYPE_OPTIONS:
            self.fractal_type_var.set(DEFAULT_FRACTAL_TYPE)
            return
        if (
            self.current_image_type == "fractal"
            and not self.is_generating
            and not self.is_exporting_video
            and not self.is_exporting_gif
        ):
            self.generate_fractal()

    def _on_rendering_mode_change(self, _event=None):
        """Persist the selected engine and refresh the current fractal if needed."""
        selected = self.rendering_mode_var.get()
        if selected not in RENDERING_MODE_OPTIONS:
            self.rendering_mode_var.set(DEFAULT_RENDERING_MODE)
            selected = DEFAULT_RENDERING_MODE
        try:
            save_rendering_mode_preference(
                selected, self.rendering_mode_preference_path
            )
        except OSError as exc:
            self.status_var.set(f"Could not save rendering preference: {exc}")
        if (
            self.current_image_type == "fractal"
            and not self.is_generating
            and not self.is_exporting_video
            and not self.is_exporting_gif
        ):
            self._render_fractal_view(self.current_fractal_view_state)

    def _on_depth_change(self, _event=None):
        """Regenerate immediately when the user selects a different color depth."""
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return
        if self.current_image_type == "fractal":
            self._render_fractal_view(self.current_fractal_view_state)
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
        source_label = (
            f"{self.current_fractal_type} fractal"
            if self.current_image_type == "fractal"
            else "Random image"
        )
        label = (
            f"{source_label} | {width} × {height} | {self.current_depth}-bit source | "
            f"{self.current_color_count:,} source colors | "
            f"{pixel_size}×{pixel_size} blocks | {render_mode}"
        )
        if self.current_depth == 1:
            label += " (black/white source)"
        elif self.current_depth == 24:
            label += " (true color RGB)"
        if self.current_image_type == "fractal":
            palette_name = (self.current_fractal_view_state or {}).get("palette_name", "Random")
            label += f" | Palette: {palette_name}"
            label += " | Drag to pan · Mouse wheel to zoom"
            if self.current_render_backend == "GPU" and self.current_render_device:
                label += f" | GPU: {self.current_render_device} (OpenCL)"
            elif self.current_render_backend == "CPU" and self.current_numba_threads:
                label += f" | CPU: {self.current_numba_threads} Numba threads"
            if self.current_render_seconds is not None:
                label += f" | Fractal render: {self.current_render_seconds:.3f}s"
            if self.current_backend_setup_seconds is not None and self.current_backend_setup_seconds >= 0.05:
                label += f" | Backend setup/calibration: {self.current_backend_setup_seconds:.2f}s"
            if self.current_render_reason and "fallback" in self.current_render_reason.lower():
                label += " | GPU fallback used"
        self.status_var.set(label)

    def _get_selected_fps(self):
        index = max(0, min(2, int(self.fps_index_var.get())))
        return VIDEO_FPS_OPTIONS[index]

    def _on_fps_change(self, value=None):
        if value is not None:
            self.fps_index_var.set(max(0, min(2, int(float(value)))))
        self.fps_label_var.set(f"{self._get_selected_fps()} FPS")

    def _on_rotation_change(self, value=None):
        if value is not None:
            self.rotation_degrees_var.set(max(0, min(VIDEO_MAX_ROTATION_DEGREES, int(round(float(value))))))
        self.rotation_degrees_label_var.set(
            f"{int(self.rotation_degrees_var.get())}°"
        )

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
        """Cancel an active video export, save position, and close the application."""
        if self.active_video_export_control is not None:
            self.active_video_export_control.cancel()
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
        """Generate a randomized view of the currently selected fractal family."""
        self._start_image_generation(
            "fractal", fractal_type=self.fractal_type_var.get()
        )

    def _start_image_generation(self, image_type, fractal_type=None, fractal_view_state=None):
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return

        settings = self.read_settings()
        if settings is None:
            return
        width, height, depth, pixel_size = settings
        bilinear = bool(self.bilinear_var.get())
        if image_type == "fractal":
            fractal_type = fractal_type or self.fractal_type_var.get()
            if fractal_type not in FRACTAL_TYPE_OPTIONS:
                messagebox.showerror("Invalid fractal type", "Choose a supported fractal family.")
                return
        else:
            fractal_type = None

        self.is_generating = True
        self._set_action_buttons()
        self.progress.pack_forget()
        rendering_mode = self.rendering_mode_var.get()
        if image_type == "fractal":
            if rendering_mode == "Automatic":
                self.status_var.set(
                    f"Benchmarking CPU vs OpenCL GPU for {fractal_type} at "
                    f"{width} × {height}..."
                )
            elif rendering_mode == "GPU":
                self.status_var.set(
                    f"Preparing OpenCL GPU rendering for {fractal_type}: "
                    f"{width} × {height}..."
                )
            else:
                saved_tuning = load_numba_thread_tuning()
                detail = (
                    f"{saved_tuning['selected_threads']} optimized CPU threads"
                    if saved_tuning else "automatic CPU thread tuning"
                )
                self.status_var.set(
                    f"Preparing Numba CPU rendering for {fractal_type}: "
                    f"{width} × {height}, {detail}..."
                )
        else:
            self.status_var.set(
                f"Generating random image: {width} × {height}, {depth}-bit, "
                f"{pixel_size}×{pixel_size} pixel blocks, "
                f"{'bilinear filtering' if bilinear else 'sharp pixel blocks'}..."
            )
        self.resize_window_to_image(width, height)

        custom_palette_stops = (
            list(self.active_palette_stops)
            if image_type == "fractal" and fractal_view_state is None and self.active_palette_stops
            else None
        )
        threading.Thread(
            target=self._image_worker,
            args=(width, height, depth, image_type, fractal_type, rendering_mode, fractal_view_state, custom_palette_stops, self.active_palette_name),
            daemon=True,
        ).start()

    def _image_worker(
        self, width, height, depth, image_type="random",
        fractal_type=DEFAULT_FRACTAL_TYPE,
        rendering_mode=DEFAULT_RENDERING_MODE,
        fractal_view_state=None,
        custom_palette_stops=None,
        custom_palette_name="Random",
    ):
        try:
            render_info = None
            resulting_view_state = None
            if image_type == "fractal":
                backend_setup_started = time.perf_counter()
                fractal_seed = (
                    int(np.random.SeedSequence().entropy)
                    if fractal_view_state is None else None
                )
                selected_backend = rendering_mode.upper()
                renderer = None
                thread_info = None

                if rendering_mode == "Automatic":
                    render_info = auto_select_fractal_backend(
                        width, height, fractal_type
                    )
                    selected_backend = render_info["backend"]
                    renderer = render_info.get("renderer")
                    thread_info = render_info.get("thread_info")
                elif selected_backend == "CPU":
                    thread_info = auto_optimize_numba_threads()
                    render_info = {
                        "backend": "CPU",
                        "device": None,
                        "cpu_threads": int(thread_info["selected_threads"]),
                        "thread_info": thread_info,
                        "reason": "CPU rendering was selected manually.",
                    }
                elif selected_backend == "GPU":
                    renderer = get_opencl_renderer()
                    render_info = {
                        "backend": "GPU",
                        "device": renderer.device,
                        "cpu_threads": None,
                        "thread_info": None,
                        "reason": "GPU rendering was selected manually.",
                        "renderer": renderer,
                    }
                else:
                    raise ValueError(f"Unsupported rendering mode: {rendering_mode!r}")

                backend_setup_seconds = time.perf_counter() - backend_setup_started
                render_started = time.perf_counter()
                try:
                    image, color_count, resulting_view_state = generate_fractal_image(
                        width,
                        height,
                        depth,
                        fractal_type=fractal_type,
                        compute_backend=selected_backend,
                        opencl_renderer=renderer,
                        view_state=fractal_view_state,
                        rng=(np.random.default_rng(fractal_seed) if fractal_seed is not None else None),
                        return_view_state=True,
                        custom_palette=custom_palette_stops,
                    )
                    resulting_view_state["palette_name"] = (
                        custom_palette_name if custom_palette_stops else
                        str(fractal_view_state.get("palette_name", "Random")) if isinstance(fractal_view_state, dict) else "Random"
                    )
                except Exception as gpu_exc:
                    # Automatic mode may recover from a transient OpenCL error.
                    # Explicit GPU mode remains strict and reports the problem.
                    if rendering_mode != "Automatic" or selected_backend != "GPU":
                        raise
                    thread_info = auto_optimize_numba_threads()
                    image, color_count, resulting_view_state = generate_fractal_image(
                        width, height, depth, fractal_type=fractal_type,
                        compute_backend="CPU", view_state=fractal_view_state,
                        rng=(np.random.default_rng(fractal_seed) if fractal_seed is not None else None),
                        return_view_state=True, custom_palette=custom_palette_stops,
                    )
                    resulting_view_state["palette_name"] = (
                        custom_palette_name if custom_palette_stops else
                        str(fractal_view_state.get("palette_name", "Random")) if isinstance(fractal_view_state, dict) else "Random"
                    )
                    render_info = {
                        "backend": "CPU",
                        "device": None,
                        "cpu_threads": int(thread_info["selected_threads"]),
                        "thread_info": thread_info,
                        "reason": f"OpenCL failed; safely fell back to CPU: {gpu_exc}",
                        "fallback": True,
                    }
                render_seconds = time.perf_counter() - render_started
                render_info["render_seconds"] = render_seconds
                render_info["backend_setup_seconds"] = backend_setup_seconds
            else:
                image, color_count = generate_random_image(width, height, depth)

            self.result_queue.put(
                (
                    "success", image, width, height, depth, color_count,
                    image_type, fractal_type, render_info, resulting_view_state,
                    bool(image_type == "fractal" and fractal_view_state is None),
                )
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
            self.show_preview()
            messagebox.showerror("Generation failed", result[1])
        else:
            (
                _, self.base_image, width, height, depth, color_count,
                image_type, fractal_type, render_info, fractal_view_state, new_fractal_generation,
            ) = result
            self.current_depth = depth
            self.current_color_count = color_count
            self.current_image_type = image_type
            self.current_render_backend = (
                render_info.get("backend") if image_type == "fractal" and render_info else None
            )
            self.current_numba_threads = (
                int(render_info["cpu_threads"])
                if image_type == "fractal" and render_info and render_info.get("cpu_threads")
                else None
            )
            self.current_render_device = (
                opencl_device_label(render_info["device"])
                if image_type == "fractal" and render_info and render_info.get("device") is not None
                else None
            )
            self.current_render_seconds = (
                float(render_info["render_seconds"])
                if image_type == "fractal" and render_info and render_info.get("render_seconds") is not None
                else None
            )
            self.current_backend_setup_seconds = (
                float(render_info["backend_setup_seconds"])
                if image_type == "fractal" and render_info and render_info.get("backend_setup_seconds") is not None
                else None
            )
            self.current_render_reason = (
                str(render_info.get("reason"))
                if image_type == "fractal" and render_info and render_info.get("reason")
                else None
            )
            if image_type == "fractal":
                self.current_fractal_type = fractal_type or DEFAULT_FRACTAL_TYPE
                self.current_fractal_view_state = fractal_view_state
            else:
                self.current_fractal_view_state = None
                self._reset_fractal_history(None)
            self._on_pixel_size_change()
            self.save_button.configure(state="normal")
            if image_type == "fractal" and isinstance(fractal_view_state, dict):
                if new_fractal_generation:
                    self._reset_fractal_history(fractal_view_state)
                    if self.gallery_auto_save_var.get():
                        try:
                            self._save_current_fractal_to_gallery(auto_saved=True)
                        except Exception as gallery_exc:
                            self.status_var.set(f"Fractal rendered; gallery save failed: {gallery_exc}")
                elif self.fractal_history_index >= 0 and self.fractal_history_index < len(self.fractal_history):
                    self.fractal_history[self.fractal_history_index] = dict(fractal_view_state)
                else:
                    self._reset_fractal_history(fractal_view_state)
            self._set_action_buttons()

        self.root.after(60, self._poll_image_result)

    def export_video(self):
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return
        if self.image is None:
            messagebox.showinfo(
                "Generate an image first",
                "Generate a random image or fractal before exporting a video.",
            )
            return

        source_type = "fractal" if self.current_image_type == "fractal" else "random"
        source_image = (
            self.image.copy().convert("RGB") if source_type == "fractal" else None
        )
        width, height = self.image.size
        if width * height > VIDEO_MAX_PIXELS:
            messagebox.showerror(
                "Video resolution too large",
                "Video export is limited to 8,294,400 pixels per frame "
                "(up to 3840 × 2160 / 4K). Reduce the selected width or height.",
            )
            return

        duration_seconds = int(self.duration_var.get())
        fps = self._get_selected_fps()
        video_codec = self.video_codec_var.get()
        bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
        rotation_degrees = int(self.rotation_degrees_var.get())
        rotation_direction = self.rotation_direction_var.get()
        total_frames = fps * duration_seconds
        source_label = "fractal_snapshot" if source_type == "fractal" else "random_images"
        export_pixel_size = int(self.pixel_size_var.get()) if source_type == "random" else 1
        quality_mode = source_type == "random" and export_pixel_size == 1
        rate_label = f"quality_qp{VIDEO_QUALITY_MODE_QP}" if quality_mode else "200mbit"
        default_name = (
            f"{source_label}_{width}x{height}_{duration_seconds}s_{fps}fps_"
            f"{normalize_video_codec(video_codec)}_{rate_label}_"
            f"rotate_{rotation_degrees}_{rotation_direction.lower()}.mp4"
        )
        output_path = filedialog.asksaveasfilename(
            title=f"Export {video_codec} video",
            initialfile=default_name,
            defaultextension=".mp4",
            filetypes=[("MP4 video (H.264 / H.265)", "*.mp4")],
        )
        if not output_path:
            return

        self.is_exporting_video = True
        video_cancel_control = VideoExportControl()
        self.active_video_export_control = video_cancel_control
        self._set_action_buttons()
        self.current_video_fps = fps
        self.current_video_frames = total_frames
        self.current_video_duration = duration_seconds
        self.current_video_codec = video_codec
        self.current_video_bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
        self.current_video_quality_mode = quality_mode
        self.progress.configure(maximum=total_frames, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        if source_type == "random":
            export_depth = int(self.current_depth or self.depth_var.get())
            export_pixel_size = int(self.pixel_size_var.get())
            export_bilinear = bool(self.bilinear_var.get())
            source_description = (
                f"fresh random frames, {export_depth}-bit, "
                f"{export_pixel_size}×{export_pixel_size} pixels"
            )
        else:
            export_depth = None
            export_pixel_size = 1
            export_bilinear = False
            source_description = "the current fractal image"
        rate_description = (
            f"constant-quality QP {VIDEO_QUALITY_MODE_QP} (bitrate varies)"
            if quality_mode else f"fixed target {VIDEO_DEFAULT_BITRATE_KBPS // 1000} Mbit/s"
        )
        self.status_var.set(
            f"Exporting {source_description} as {video_codec}: {width} × {height}, "
            f"{duration_seconds} seconds, {fps} fps, {rate_description}, "
            f"rotating {rotation_degrees}° {rotation_direction.lower()}..."
        )

        threading.Thread(
            target=self._video_worker,
            args=(
                output_path, source_type, source_image, width, height,
                duration_seconds, fps, bitrate_kbps, rotation_degrees,
                rotation_direction, export_depth, export_pixel_size,
                export_bilinear, self.rendering_mode_var.get(), video_codec,
                video_cancel_control,
            ),
            daemon=True,
        ).start()

    def export_gif(self):
        """Export a preset-resolution animated GIF at 30 FPS."""
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
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

    def cancel_video_export(self):
        """Cancel the active H.264/H.265 or Fractal Animation Studio export."""
        control = self.active_video_export_control
        if control is None or control.cancelled:
            return
        control.cancel()
        self.cancel_video_button.configure(text="Cancelling...", state="disabled")
        self.status_var.set("Cancelling export and removing the incomplete output file...")

    def _video_worker(
        self,
        output_path,
        source_type,
        source_image,
        width,
        height,
        duration_seconds,
        fps,
        bitrate_kbps,
        rotation_degrees,
        rotation_direction,
        export_depth,
        export_pixel_size,
        export_bilinear,
        rendering_mode="Automatic",
        video_codec=VIDEO_DEFAULT_CODEC,
        cancel_control=None,
    ):
        try:
            if cancel_control is not None:
                cancel_control.check()
            def report_progress(frame_number):
                self.video_queue.put(("progress", frame_number))

            if source_type == "random":
                # Every output frame gets a fresh pattern. GPU/Automatic uses
                # OpenCL to generate and rotate batches before FFmpeg encoding.
                video_info = encode_random_h264_video(
                    output_path,
                    width,
                    height,
                    export_depth,
                    duration_seconds=duration_seconds,
                    fps=fps,
                    bitrate_kbps=bitrate_kbps,
                    pixel_size=export_pixel_size,
                    progress_callback=report_progress,
                    bilinear=export_bilinear,
                    rotation_degrees=rotation_degrees,
                    rotation_direction=rotation_direction,
                    compute_backend=rendering_mode,
                    video_codec=video_codec,
                    cancel_control=cancel_control,
                )
            else:
                video_info = encode_rotating_image_h264_video(
                    output_path,
                    source_image,
                    duration_seconds=duration_seconds,
                    fps=fps,
                    bitrate_kbps=bitrate_kbps,
                    rotation_degrees=rotation_degrees,
                    rotation_direction=rotation_direction,
                    progress_callback=report_progress,
                    compute_backend=rendering_mode,
                    video_codec=video_codec,
                    cancel_control=cancel_control,
                )
            if cancel_control is not None:
                cancel_control.check()
            if not isinstance(video_info, dict):
                video_info = None
            self.video_queue.put(("success", output_path, video_info))
        except VideoExportCancelled:
            removed, cleanup_error = _remove_incomplete_video_file(output_path)
            self.video_queue.put(("cancelled", output_path, removed, cleanup_error))
        except Exception as exc:
            if cancel_control is not None and cancel_control.cancelled:
                removed, cleanup_error = _remove_incomplete_video_file(output_path)
                self.video_queue.put(("cancelled", output_path, removed, cleanup_error))
            else:
                self.video_queue.put(("error", str(exc)))

    def _poll_video_result(self):
        try:
            while True:
                result = self.video_queue.get_nowait()
                if result[0] == "progress":
                    if self.active_video_export_control is not None and self.active_video_export_control.cancelled:
                        continue
                    completed = result[1]
                    self.progress.configure(value=completed)
                    self.status_var.set(
                        f"Encoding {self.current_video_codec}: frame {completed}/{self.current_video_frames} "
                        f"({completed / self.current_video_fps:.1f}/"
                        f"{self.current_video_duration} seconds)"
                    )
                elif result[0] == "success":
                    self.is_exporting_video = False
                    self.active_video_export_control = None
                    self.progress.configure(value=self.current_video_frames)
                    self._set_action_buttons()
                    info = result[2] if len(result) > 2 and isinstance(result[2], dict) else {}
                    fallback_reason = info.get("fallback_reason")
                    encoder_fallback = info.get("encoder_fallback_reason")
                    if info.get("backend") == "GPU":
                        renderer_label = f"OpenCL GPU: {info.get('device') or 'GPU'}"
                    elif fallback_reason:
                        renderer_label = "CPU renderer (Automatic OpenCL fallback)"
                    else:
                        renderer_label = "CPU renderer"
                    codec_label = info.get("codec", video_codec_label(self.current_video_codec))
                    encoder_label = info.get("encoder_label", f"{codec_label} encoder")
                    self.status_var.set(
                        f"Saved {codec_label} MP4 ({encoder_label}; {renderer_label}): {result[1]}"
                    )
                    notes = []
                    if fallback_reason:
                        notes.append(
                            "Automatic rendering mode used the CPU because OpenCL was unavailable:\n"
                            + fallback_reason
                        )
                    if encoder_fallback:
                        notes.append(
                            f"NVENC was unavailable, so {codec_label} was encoded on the CPU:\n"
                            + encoder_fallback
                        )
                    completion_note = "\n\n" + "\n\n".join(notes) if notes else ""
                    quality_mode = bool(info.get("quality_mode", getattr(self, "current_video_quality_mode", False)))
                    rate_description = (
                        f"Rate control: {info.get('rate_control', f'Constant QP {VIDEO_QUALITY_MODE_QP}')} (bitrate varies)\n"
                        if quality_mode else
                        f"Target bitrate: {VIDEO_DEFAULT_BITRATE_KBPS // 1000} Mbit/s\n"
                    )
                    messagebox.showinfo(
                        f"{codec_label} video export complete",
                        f"Your {self.current_video_duration}-second, "
                        f"{self.current_video_fps}-fps {codec_label} MP4 video has been saved.\n\n"
                        + rate_description
                        + f"Video encoder: {encoder_label}\n"
                        + f"Frame renderer: {renderer_label}\n\n" + result[1] + completion_note,
                    )
                    self.progress.pack_forget()
                elif result[0] == "cancelled":
                    self.is_exporting_video = False
                    self.active_video_export_control = None
                    self.progress.configure(value=0)
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    removed = result[2] if len(result) > 2 else not os.path.exists(result[1])
                    cleanup_error = result[3] if len(result) > 3 else None
                    if removed:
                        self.status_var.set("Video export cancelled. Incomplete MP4 deleted.")
                    else:
                        self.status_var.set("Video export cancelled, but the incomplete MP4 could not be deleted.")
                        messagebox.showwarning(
                            "Incomplete video could not be deleted",
                            "The export was cancelled, but Windows still has the incomplete file locked. "
                            "Close any application using it and delete it manually.\n\n"
                            f"File: {result[1]}\nReason: {cleanup_error or 'File is still in use.'}",
                        )
                elif result[0] == "error":
                    self.is_exporting_video = False
                    self.active_video_export_control = None
                    self._set_action_buttons()
                    self.progress.pack_forget()
                    self.status_var.set("Video export failed.")
                    messagebox.showerror("Video export failed", result[1])
        except queue.Empty:
            pass

        self.root.after(80, self._poll_video_result)

    # ------------------------------------------------------------------
    # Fractal workspace: bookmarks, history, gallery and custom palettes
    # ------------------------------------------------------------------
    def _save_gallery_auto_save_preference(self):
        try:
            save_gallery_auto_save(self.gallery_auto_save_var.get())
        except OSError as exc:
            messagebox.showerror("Gallery preference", f"Could not save gallery preference: {exc}")

    def save_current_bookmark(self):
        if self.current_image_type != "fractal" or not isinstance(self.current_fractal_view_state, dict):
            messagebox.showinfo("Fractal bookmark", "Generate or load a fractal before saving a bookmark.")
            return
        name = simpledialog.askstring(
            "Save fractal bookmark", "Bookmark name:", parent=self.root,
            initialvalue=f"{self.current_fractal_type} view",
        )
        if not name or not name.strip():
            return
        width, height = self.base_image.size if self.base_image is not None else DEFAULT_IMAGE_RESOLUTION
        record = {
            "name": name.strip(),
            "created": datetime.now().isoformat(timespec="seconds"),
            "fractal_type": self.current_fractal_type,
            "view_state": dict(self.current_fractal_view_state),
            "width": int(width), "height": int(height),
            "depth": int(self.current_depth or int(self.depth_var.get())),
            "pixel_size": int(self.pixel_size_var.get()),
            "bilinear": bool(self.bilinear_var.get()),
        }
        self.bookmarks.append(record)
        try:
            save_fractal_bookmarks(self.bookmarks, self.bookmarks_path)
            self.status_var.set(f"Saved fractal bookmark: {record['name']}")
        except Exception as exc:
            self.bookmarks.pop()
            messagebox.showerror("Bookmark save failed", str(exc))

    def _restore_saved_view_settings(self, record):
        state = dict(record.get("view_state", {}))
        fractal_type = record.get("fractal_type", state.get("fractal_type", DEFAULT_FRACTAL_TYPE))
        if fractal_type not in FRACTAL_TYPE_OPTIONS:
            raise ValueError("The saved fractal type is not supported by this version.")
        width = int(record.get("width", self.width_var.get()))
        height = int(record.get("height", self.height_var.get()))
        if width <= 0 or height <= 0 or width * height > IMAGE_MAX_PIXELS:
            raise ValueError("The saved image dimensions are no longer supported.")
        self.width_var.set(str(width))
        self.height_var.set(str(height))
        for label, preset_width, preset_height in IMAGE_RESOLUTION_PRESETS:
            if (preset_width, preset_height) == (width, height):
                self.resolution_var.set(label)
                break
        depth = int(record.get("depth", self.depth_var.get()))
        if depth in COLOR_DEPTH_OPTIONS:
            self.depth_var.set(str(depth))
        pixel_size = int(record.get("pixel_size", self.pixel_size_var.get()))
        if 1 <= pixel_size <= 32:
            self.pixel_size_var.set(pixel_size)
            self._on_pixel_size_change()
        self.bilinear_var.set(bool(record.get("bilinear", self.bilinear_var.get())))
        state["fractal_type"] = fractal_type
        self.current_fractal_type = fractal_type
        self.fractal_type_var.set(fractal_type)
        self.current_image_type = "fractal"
        if state.get("palette_stops"):
            self.active_palette_stops = normalize_palette_stops(state["palette_stops"])
            self.active_palette_name = str(state.get("palette_name", "Custom"))
            save_active_palette(self.active_palette_name)
        else:
            self.active_palette_stops = None
            self.active_palette_name = "Random"
            save_active_palette("Random")
        self._reset_fractal_history(state)
        self._render_fractal_view(state)

    def manage_bookmarks_dialog(self):
        self.bookmarks = load_fractal_bookmarks(self.bookmarks_path)
        window = tk.Toplevel(self.root)
        window.title("Fractal Bookmarks")
        window.transient(self.root)
        window.geometry("620x390")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        listbox = tk.Listbox(window, height=14, activestyle="dotbox")
        listbox.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=10, pady=10)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=listbox.yview)
        scrollbar.grid(row=0, column=3, sticky="ns", pady=10)
        listbox.configure(yscrollcommand=scrollbar.set)

        def refresh():
            listbox.delete(0, "end")
            for item in self.bookmarks:
                state = item.get("view_state", {})
                zoom = float(state.get("home_horizontal_span", 1.0)) / max(1e-14, float(state.get("horizontal_span", 1.0)))
                listbox.insert("end", f"{item.get('name', 'Untitled')}  |  {item.get('fractal_type', 'Fractal')}  |  {zoom:.2f}× zoom  |  {item.get('created', '')}")

        def load_selected():
            selection = listbox.curselection()
            if not selection:
                messagebox.showinfo("Fractal Bookmarks", "Select a bookmark first.", parent=window)
                return
            try:
                self._restore_saved_view_settings(self.bookmarks[selection[0]])
                window.destroy()
            except Exception as exc:
                messagebox.showerror("Could not load bookmark", str(exc), parent=window)

        def delete_selected():
            selection = listbox.curselection()
            if not selection:
                return
            item = self.bookmarks[selection[0]]
            if not messagebox.askyesno("Delete bookmark", f"Delete '{item.get('name', 'Untitled')}'?", parent=window):
                return
            del self.bookmarks[selection[0]]
            try:
                save_fractal_bookmarks(self.bookmarks, self.bookmarks_path)
                refresh()
            except Exception as exc:
                messagebox.showerror("Bookmark delete failed", str(exc), parent=window)

        ttk.Button(window, text="Load selected", command=load_selected).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(window, text="Delete selected", command=delete_selected).grid(row=1, column=1, sticky="w", padx=4, pady=(0, 10))
        ttk.Button(window, text="Close", command=window.destroy).grid(row=1, column=2, sticky="e", padx=10, pady=(0, 10))
        listbox.bind("<Double-Button-1>", lambda _event: load_selected())
        refresh()

    def _save_current_fractal_to_gallery(self, auto_saved=False):
        if self.current_image_type != "fractal" or self.image is None or not isinstance(self.current_fractal_view_state, dict):
            return None
        width, height = self.image.size
        metadata = {
            "name": f"{self.current_fractal_type} – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "fractal_type": self.current_fractal_type,
            "view_state": dict(self.current_fractal_view_state),
            "width": int(width), "height": int(height),
            "depth": int(self.current_depth or 24),
            "pixel_size": int(self.pixel_size_var.get()),
            "bilinear": bool(self.bilinear_var.get()),
            "palette_name": self.active_palette_name,
            "render_backend": self.current_render_backend,
            "render_seconds": self.current_render_seconds,
            "auto_saved": bool(auto_saved),
        }
        return save_gallery_entry(self.image, metadata)

    def open_fractal_gallery(self):
        window = tk.Toplevel(self.root)
        window.title("Fractal Gallery")
        window.transient(self.root)
        window.geometry("760x460")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        listbox = tk.Listbox(window, height=16, activestyle="dotbox")
        listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=10, pady=10)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=listbox.yview)
        scrollbar.grid(row=0, column=4, sticky="ns", pady=10)
        listbox.configure(yscrollcommand=scrollbar.set)
        entries = []

        def refresh():
            nonlocal entries
            entries = list_gallery_entries()
            listbox.delete(0, "end")
            for item in entries:
                listbox.insert("end", f"{item.get('name', item.get('fractal_type', 'Fractal'))}  |  {item.get('width')}×{item.get('height')}  |  {item.get('created', '')}")

        def load_selected():
            selection = listbox.curselection()
            if not selection:
                return
            try:
                self._restore_saved_view_settings(entries[selection[0]])
                window.destroy()
            except Exception as exc:
                messagebox.showerror("Gallery load failed", str(exc), parent=window)

        def delete_selected():
            selection = listbox.curselection()
            if not selection:
                return
            entry = entries[selection[0]]
            if not messagebox.askyesno("Delete gallery item", f"Delete '{entry.get('name', 'Fractal')}'?", parent=window):
                return
            for path in (entry.get("metadata_file"), entry.get("image_path")):
                try:
                    if path and os.path.isfile(path):
                        os.remove(path)
                except OSError as exc:
                    messagebox.showerror("Gallery delete failed", str(exc), parent=window)
                    return
            refresh()

        def open_folder():
            folder = get_gallery_directory()
            os.makedirs(folder, exist_ok=True)
            try:
                if os.name == "nt":
                    os.startfile(folder)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as exc:
                messagebox.showerror("Could not open gallery folder", str(exc), parent=window)

        ttk.Button(window, text="Load selected", command=load_selected).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(window, text="Delete selected", command=delete_selected).grid(row=1, column=1, sticky="w", padx=4, pady=(0, 10))
        ttk.Button(window, text="Open folder", command=open_folder).grid(row=1, column=2, sticky="w", padx=4, pady=(0, 10))
        ttk.Button(window, text="Close", command=window.destroy).grid(row=1, column=3, sticky="e", padx=10, pady=(0, 10))
        listbox.bind("<Double-Button-1>", lambda _event: load_selected())
        refresh()

    def open_palette_editor(self):
        window = tk.Toplevel(self.root)
        window.title("Custom Fractal Color Palettes")
        window.transient(self.root)
        window.geometry("650x470")
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)
        window.rowconfigure(1, weight=1)

        ttk.Label(window, text="Saved palettes").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        ttk.Label(window, text="Gradient color stops").grid(row=0, column=1, sticky="w", padx=10, pady=(10, 4))
        saved_list = tk.Listbox(window, height=14, activestyle="dotbox")
        saved_list.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=4)
        stops_list = tk.Listbox(window, height=14, activestyle="dotbox")
        stops_list.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=4)
        name_var = tk.StringVar(value="My Gradient")
        ttk.Label(window, text="Palette name:").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        name_entry = ttk.Entry(window, textvariable=name_var)
        name_entry.grid(row=3, column=0, sticky="ew", padx=10)
        draft = ["#050816", "#00B7C7", "#F9C74F", "#FFFFFF"]

        def refresh_stops():
            stops_list.delete(0, "end")
            for stop in draft:
                stops_list.insert("end", stop)

        def refresh_saved(select_name=None):
            saved_list.delete(0, "end")
            saved_list.insert("end", "Random (built-in spectrum)")
            for name in sorted(self.custom_palettes, key=str.casefold):
                saved_list.insert("end", name)
                if name == select_name:
                    saved_list.selection_set(saved_list.size() - 1)
            if select_name == "Random":
                saved_list.selection_set(0)

        def load_saved(_event=None):
            selection = saved_list.curselection()
            if not selection:
                return
            index = selection[0]
            if index == 0:
                name_var.set("Random")
                draft[:] = ["#000000", "#00B7C7", "#FFFFFF"]
            else:
                selected_name = saved_list.get(index)
                name_var.set(selected_name)
                draft[:] = list(self.custom_palettes.get(selected_name, draft))
            refresh_stops()

        def add_stop():
            _rgb, color = colorchooser.askcolor(parent=window, title="Add gradient color")
            if color:
                if len(draft) >= 16:
                    messagebox.showinfo("Palette editor", "A gradient can have at most 16 stops.", parent=window)
                    return
                draft.append(color.upper())
                refresh_stops()
                stops_list.selection_set(stops_list.size() - 1)

        def edit_stop():
            selection = stops_list.curselection()
            if not selection:
                return
            index = selection[0]
            _rgb, color = colorchooser.askcolor(color=draft[index], parent=window, title="Edit gradient color")
            if color:
                draft[index] = color.upper()
                refresh_stops()
                stops_list.selection_set(index)

        def remove_stop():
            selection = stops_list.curselection()
            if not selection:
                return
            if len(draft) <= 2:
                messagebox.showinfo("Palette editor", "A gradient needs at least two color stops.", parent=window)
                return
            del draft[selection[0]]
            refresh_stops()

        def save_palette():
            name = name_var.get().strip()
            try:
                if not name or name.lower() == "random":
                    raise ValueError("Choose a palette name other than Random.")
                stops = normalize_palette_stops(draft)
                self.custom_palettes[name] = stops
                save_custom_palettes(self.custom_palettes, self.custom_palettes_path)
                refresh_saved(name)
                self.status_var.set(f"Saved custom palette: {name}")
            except Exception as exc:
                messagebox.showerror("Palette save failed", str(exc), parent=window)

        def apply_palette():
            name = name_var.get().strip()
            if name.lower() == "random":
                self.active_palette_name = "Random"
                self.active_palette_stops = None
                save_active_palette("Random")
                if self.current_image_type == "fractal" and isinstance(self.current_fractal_view_state, dict):
                    state = dict(self.current_fractal_view_state)
                    state["palette_stops"] = None
                    state["palette_name"] = "Random"
                    self._commit_fractal_view(state)
                else:
                    self.status_var.set("Random fractal color spectrum selected for the next generation.")
                return
            try:
                stops = normalize_palette_stops(draft)
                if name not in self.custom_palettes:
                    self.custom_palettes[name] = stops
                    save_custom_palettes(self.custom_palettes, self.custom_palettes_path)
                self.active_palette_name = name
                self.active_palette_stops = stops
                save_active_palette(name)
                if self.current_image_type == "fractal" and isinstance(self.current_fractal_view_state, dict):
                    state = dict(self.current_fractal_view_state)
                    state["palette_stops"] = list(stops)
                    state["palette_name"] = name
                    self._commit_fractal_view(state)
                else:
                    self.status_var.set(f"Custom palette '{name}' will be used for the next fractal.")
            except Exception as exc:
                messagebox.showerror("Palette apply failed", str(exc), parent=window)

        def delete_palette():
            selection = saved_list.curselection()
            if not selection or selection[0] == 0:
                return
            name = saved_list.get(selection[0])
            if not messagebox.askyesno("Delete palette", f"Delete '{name}'?", parent=window):
                return
            self.custom_palettes.pop(name, None)
            save_custom_palettes(self.custom_palettes, self.custom_palettes_path)
            if self.active_palette_name == name:
                self.active_palette_name = "Random"
                self.active_palette_stops = None
                save_active_palette("Random")
            refresh_saved()

        saved_list.bind("<<ListboxSelect>>", load_saved)
        saved_list.bind("<Double-Button-1>", load_saved)
        controls = ttk.Frame(window, padding=10)
        controls.grid(row=4, column=0, columnspan=2, sticky="ew")
        for text, command in (
            ("Add stop", add_stop), ("Edit selected", edit_stop),
            ("Remove selected", remove_stop), ("Save palette", save_palette),
            ("Apply palette", apply_palette), ("Delete palette", delete_palette),
            ("Close", window.destroy),
        ):
            ttk.Button(controls, text=text, command=command).pack(side="left", padx=3)
        refresh_saved(self.active_palette_name)
        refresh_stops()

    # ------------------------------------------------------------------
    # Batch fractal generation
    # ------------------------------------------------------------------
    def open_batch_generation_dialog(self):
        if (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation):
            return
        window = tk.Toplevel(self.root)
        window.title("Batch Fractal Generation")
        window.transient(self.root)
        window.resizable(False, False)
        count_var = tk.StringVar(value="100")
        family_var = tk.StringVar(value="Random (all seven families)")
        folder_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Pictures", "Pixel Generator Batch"))
        ttk.Label(window, text="Number of fractals:").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        count_combo = ttk.Combobox(window, textvariable=count_var, values=[str(v) for v in BATCH_GENERATION_COUNTS], width=12, state="readonly")
        count_combo.grid(row=0, column=1, sticky="w", padx=8, pady=(12, 4))
        ttk.Label(window, text="Fractal family:").grid(row=1, column=0, sticky="w", padx=12, pady=4)
        family_combo = ttk.Combobox(window, textvariable=family_var, values=["Random (all seven families)"] + list(FRACTAL_TYPE_OPTIONS), width=28, state="readonly")
        family_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(window, text="Output folder:").grid(row=2, column=0, sticky="w", padx=12, pady=4)
        ttk.Entry(window, textvariable=folder_var, width=42).grid(row=2, column=1, sticky="ew", padx=8, pady=4)

        def choose_folder():
            selected = filedialog.askdirectory(parent=window, initialdir=folder_var.get())
            if selected:
                folder_var.set(selected)

        ttk.Button(window, text="Browse...", command=choose_folder).grid(row=2, column=2, padx=(0, 12), pady=4)
        width, height = int(self.width_var.get()), int(self.height_var.get())
        ttk.Label(window, text=f"Current output: {width} × {height}, {self.depth_var.get()}-bit, {self.rendering_mode_var.get()} renderer").grid(row=3, column=0, columnspan=3, sticky="w", padx=12, pady=8)
        ttk.Label(window, text="Each image is saved as PNG with a matching JSON file containing its fractal coordinates and parameters.", wraplength=520).grid(row=4, column=0, columnspan=3, sticky="w", padx=12, pady=4)

        def start_batch():
            try:
                count = int(count_var.get())
                if count not in BATCH_GENERATION_COUNTS:
                    raise ValueError("Choose either 100 or 1,000 images.")
                folder = folder_var.get().strip()
                if not folder:
                    raise ValueError("Choose an output folder.")
                os.makedirs(folder, exist_ok=True)
                settings = self.read_settings()
                if settings is None:
                    return
                width, height, depth, pixel_size = settings
            except Exception as exc:
                messagebox.showerror("Batch settings", str(exc), parent=window)
                return
            if count == 1000 and not messagebox.askyesno(
                "Generate 1,000 fractals?",
                f"This will render and save 1,000 images at {width}×{height}. It may take a long time and use substantial disk space. Continue?",
                parent=window,
            ):
                return
            family = family_var.get()
            window.destroy()
            self._start_batch_generation(count, family, folder, width, height, depth, pixel_size)

        button_row = ttk.Frame(window, padding=12)
        button_row.grid(row=5, column=0, columnspan=3, sticky="e")
        ttk.Button(button_row, text="Start batch", command=start_batch).pack(side="right", padx=4)
        ttk.Button(button_row, text="Cancel", command=window.destroy).pack(side="right", padx=4)

    def _start_batch_generation(self, count, family, folder, width, height, depth, pixel_size):
        if self.is_batch_generating:
            return
        self.is_batch_generating = True
        self.batch_cancel_event.clear()
        self._set_action_buttons()
        self.progress.configure(maximum=count, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.status_var.set(f"Preparing batch of {count} fractals...")
        window = tk.Toplevel(self.root)
        window.title("Batch Generation Progress")
        window.transient(self.root)
        self.batch_window = window
        ttk.Label(window, text=f"Generating {count} fractals").pack(padx=15, pady=(14, 4))
        self.batch_status_label = ttk.Label(window, text="Starting...")
        self.batch_status_label.pack(padx=15, pady=4)
        self.batch_progress = ttk.Progressbar(window, maximum=count, value=0, length=420)
        self.batch_progress.pack(padx=15, pady=8)
        ttk.Button(window, text="Cancel batch", command=self.batch_cancel_event.set).pack(pady=(2, 14))
        threading.Thread(
            target=self._batch_generation_worker,
            args=(count, family, folder, width, height, depth, pixel_size,
                  bool(self.bilinear_var.get()), self.rendering_mode_var.get(),
                  list(self.active_palette_stops) if self.active_palette_stops else None,
                  self.active_palette_name, bool(self.gallery_auto_save_var.get())),
            daemon=True,
        ).start()

    def _batch_generation_worker(self, count, family, folder, width, height, depth, pixel_size, bilinear, rendering_mode, palette_stops, palette_name, auto_save_gallery):
        completed = 0
        rng = np.random.default_rng()
        families = list(FRACTAL_TYPE_OPTIONS)
        try:
            gallery_dir = get_gallery_directory()
            for index in range(int(count)):
                if self.batch_cancel_event.is_set():
                    break
                fractal_type = str(rng.choice(families)) if family.startswith("Random") else family
                backend, renderer, _info = resolve_fractal_render_backend(width, height, fractal_type, rendering_mode)
                image, color_count, view_state = generate_fractal_image(
                    width, height, depth, fractal_type=fractal_type,
                    compute_backend=backend, opencl_renderer=renderer, rng=rng,
                    return_view_state=True, custom_palette=palette_stops,
                )
                view_state["palette_name"] = palette_name
                final_image = pixelate_image(image, pixel_size, bilinear=bilinear)
                filename = f"fractal_{index + 1:04d}_{fractal_type.lower().replace(' ', '_').replace('(', '').replace(')', '')}_{width}x{height}.png"
                output_path = os.path.join(folder, filename)
                final_image.save(output_path, "PNG", optimize=False)
                metadata = {
                    "name": filename, "fractal_type": fractal_type,
                    "view_state": view_state, "width": width, "height": height,
                    "depth": depth, "pixel_size": pixel_size, "bilinear": bilinear,
                    "palette_name": palette_name, "batch_index": index + 1,
                }
                _atomic_write_json(os.path.splitext(output_path)[0] + ".json", metadata)
                if auto_save_gallery:
                    try:
                        save_gallery_entry(final_image, metadata, gallery_dir)
                    except Exception:
                        pass
                completed = index + 1
                self.batch_queue.put(("progress", completed, count, fractal_type))
            self.batch_queue.put(("success", completed, count, folder, self.batch_cancel_event.is_set()))
        except Exception as exc:
            self.batch_queue.put(("error", str(exc), completed, count))

    def _poll_batch_result(self):
        try:
            while True:
                item = self.batch_queue.get_nowait()
                if item[0] == "progress":
                    _, completed, total, family = item
                    if self.batch_progress is not None:
                        self.batch_progress.configure(value=completed)
                    if self.batch_status_label is not None:
                        self.batch_status_label.configure(text=f"{completed:,} / {total:,} completed — {family}")
                    self.status_var.set(f"Batch generation: {completed:,}/{total:,} fractals")
                elif item[0] == "success":
                    _, completed, total, folder, cancelled = item
                    self.is_batch_generating = False
                    self._set_action_buttons()
                    self.progress.pack_forget()
                    if self.batch_window is not None:
                        self.batch_window.destroy()
                        self.batch_window = None
                    message = f"Saved {completed:,} of {total:,} fractals to:\n\n{folder}"
                    if cancelled:
                        message = "Batch cancelled.\n\n" + message
                    self.status_var.set(f"Batch complete: {completed:,}/{total:,} fractals saved")
                    messagebox.showinfo("Batch generation complete", message)
                elif item[0] == "error":
                    _, error, completed, total = item
                    self.is_batch_generating = False
                    self._set_action_buttons()
                    self.progress.pack_forget()
                    if self.batch_window is not None:
                        self.batch_window.destroy()
                        self.batch_window = None
                    messagebox.showerror("Batch generation failed", f"{error}\n\nCompleted before failure: {completed}/{total}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_batch_result)

    # ------------------------------------------------------------------
    # Fractal Animation Studio
    # ------------------------------------------------------------------
    def open_fractal_animation_studio(self):
        if self.current_image_type != "fractal" or not isinstance(self.current_fractal_view_state, dict):
            messagebox.showinfo("Fractal Animation Studio", "Generate or load a fractal first, then open the Animation Studio.")
            return
        if self.is_generating or self.is_batch_generating or self.is_exporting_animation:
            return
        window = tk.Toplevel(self.root)
        window.title("Fractal Animation Studio")
        window.transient(self.root)
        window.resizable(False, False)
        duration_var = tk.StringVar(value=str(ANIMATION_DEFAULT_SECONDS))
        fps_var = tk.StringVar(value=str(ANIMATION_DEFAULT_FPS))
        zoom_var = tk.StringVar(value="25")
        target_x_var = tk.StringVar(value="50")
        target_y_var = tk.StringVar(value="50")
        rotation_var = tk.IntVar(value=int(self.rotation_degrees_var.get()))
        rotation_direction_var = tk.StringVar(value=self.rotation_direction_var.get())
        animation_codec_var = tk.StringVar(value=self.video_codec_var.get())
        animation_gif_resolution_var = tk.StringVar(value=self.gif_resolution_var.get())
        ttk.Label(window, text=f"Current fractal: {self.current_fractal_type}").grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 8))
        ttk.Label(window, text="Duration (seconds):").grid(row=1, column=0, sticky="w", padx=14, pady=5)
        ttk.Spinbox(window, from_=1, to=60, textvariable=duration_var, width=12).grid(row=1, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Frame rate:").grid(row=2, column=0, sticky="w", padx=14, pady=5)
        ttk.Combobox(window, textvariable=fps_var, values=["30", "60", "120"], width=10, state="readonly").grid(row=2, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Zoom factor:").grid(row=3, column=0, sticky="w", padx=14, pady=5)
        ttk.Combobox(window, textvariable=zoom_var, values=[str(v) for v in ANIMATION_ZOOM_OPTIONS], width=10, state="readonly").grid(row=3, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Target position X (%):").grid(row=4, column=0, sticky="w", padx=14, pady=5)
        ttk.Spinbox(window, from_=0, to=100, textvariable=target_x_var, width=12).grid(row=4, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Target position Y (%):").grid(row=5, column=0, sticky="w", padx=14, pady=5)
        ttk.Spinbox(window, from_=0, to=100, textvariable=target_y_var, width=12).grid(row=5, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Rotation angle (0–720°):").grid(row=6, column=0, sticky="w", padx=14, pady=5)
        rotation_frame = ttk.Frame(window)
        rotation_frame.grid(row=6, column=1, sticky="w", padx=10, pady=5)
        rotation_label_var = tk.StringVar(value=f"{rotation_var.get()}°")
        def update_animation_rotation(value=None):
            if value is not None:
                rotation_var.set(max(0, min(VIDEO_MAX_ROTATION_DEGREES, int(round(float(value))))))
            rotation_label_var.set(f"{rotation_var.get()}°")
        tk.Scale(
            rotation_frame, variable=rotation_var, from_=0, to=VIDEO_MAX_ROTATION_DEGREES,
            resolution=1, orient="horizontal", showvalue=False,
            length=220, width=14, sliderlength=18,
            highlightthickness=0, borderwidth=0,
            command=update_animation_rotation,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(rotation_frame, textvariable=rotation_label_var, width=5).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(window, text="Rotation direction:").grid(row=7, column=0, sticky="w", padx=14, pady=5)
        ttk.Combobox(
            window, textvariable=rotation_direction_var,
            values=["Clockwise", "Counterclockwise"],
            width=18, state="readonly",
        ).grid(row=7, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(window, text="Video codec:").grid(row=8, column=0, sticky="w", padx=14, pady=5)
        animation_format_frame = ttk.Frame(window)
        animation_format_frame.grid(row=8, column=1, sticky="w", padx=10, pady=5)
        ttk.Combobox(
            animation_format_frame, textvariable=animation_codec_var,
            values=VIDEO_CODEC_OPTIONS, width=14, state="readonly",
        ).pack(side="left", padx=(0, 12))
        ttk.Label(window, text=f"MP4 output resolution: {self.base_image.width} × {self.base_image.height}\nMP4 target bitrate: {VIDEO_DEFAULT_BITRATE_KBPS // 1000} Mbit/s\nRenderer: {self.rendering_mode_var.get()}\nThe animation smoothly zooms toward the selected target while rotating.", justify="left").grid(row=9, column=0, columnspan=2, sticky="w", padx=14, pady=8)
        ttk.Label(window, text="GIF resolution:").grid(row=10, column=0, sticky="w", padx=14, pady=5)
        ttk.Combobox(
            window,
            textvariable=animation_gif_resolution_var,
            values=[format_gif_resolution(size) for size in GIF_RESOLUTION_OPTIONS],
            width=12,
            state="readonly",
        ).grid(row=10, column=1, sticky="w", padx=10, pady=5)
        ttk.Label(
            window,
            text=f"Animated GIF uses {GIF_FPS} FPS and supports durations of {GIF_MIN_SECONDS}–{GIF_MAX_SECONDS} seconds. All 13 standard GIF resolutions are available.",
            justify="left",
        ).grid(row=11, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 8))

        def start_animation():
            try:
                duration = int(duration_var.get())
                fps = int(fps_var.get())
                zoom = float(zoom_var.get())
                x_ratio = float(target_x_var.get()) / 100.0
                y_ratio = float(target_y_var.get()) / 100.0
                rotation_degrees = int(rotation_var.get())
                rotation_direction = rotation_direction_var.get()
                animation_codec = animation_codec_var.get()
                animation_bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
                if not 1 <= duration <= 60 or fps not in VIDEO_FPS_OPTIONS or not 1 < zoom <= 10000:
                    raise ValueError("Check duration, frame rate and zoom factor.")
                if not 0 <= rotation_degrees <= VIDEO_MAX_ROTATION_DEGREES or rotation_direction not in ("Clockwise", "Counterclockwise"):
                    raise ValueError("Check the rotation angle and direction.")
                if not (0 <= x_ratio <= 1 and 0 <= y_ratio <= 1):
                    raise ValueError("Target position percentages must be between 0 and 100.")
                width, height, depth, pixel_size = self.read_settings()
                if width is None:
                    return
                if width * height > VIDEO_MAX_PIXELS:
                    raise ValueError("Animation export is limited to 4K (8,294,400 pixels per frame). Choose a smaller resolution.")
                filename = (
                    f"{self.current_fractal_type.lower().replace(' ', '_')}_zoom_{zoom:g}x_"
                    f"rotate_{rotation_degrees}_{rotation_direction.lower()}_"
                    f"{normalize_video_codec(animation_codec)}_{animation_bitrate_kbps // 1000}mbit_"
                    f"{duration}s_{fps}fps.mp4"
                )
                output_path = filedialog.asksaveasfilename(parent=window, title=f"Save {animation_codec} fractal animation", initialfile=filename, defaultextension=".mp4", filetypes=[("MP4 video (H.264 / H.265)", "*.mp4")])
                if not output_path:
                    return
                state = dict(self.current_fractal_view_state)
                fractal_type = self.current_fractal_type
                bilinear = bool(self.bilinear_var.get())
                rendering_mode = self.rendering_mode_var.get()
                window.destroy()
                self._start_fractal_animation_export(
                    output_path, width, height, depth, pixel_size, bilinear,
                    fractal_type, state, duration, fps, zoom, x_ratio, y_ratio,
                    rendering_mode, rotation_degrees, rotation_direction,
                    animation_codec, animation_bitrate_kbps,
                )
            except Exception as exc:
                messagebox.showerror("Animation settings", str(exc), parent=window)

        def start_gif_animation():
            try:
                duration = int(duration_var.get())
                zoom = float(zoom_var.get())
                x_ratio = float(target_x_var.get()) / 100.0
                y_ratio = float(target_y_var.get()) / 100.0
                rotation_degrees = int(rotation_var.get())
                rotation_direction = rotation_direction_var.get()
                gif_resolution = normalize_gif_resolution(animation_gif_resolution_var.get())
                if not GIF_MIN_SECONDS <= duration <= GIF_MAX_SECONDS:
                    raise ValueError(
                        f"Animated GIF duration must be between {GIF_MIN_SECONDS} and "
                        f"{GIF_MAX_SECONDS} seconds. Reduce the duration before exporting GIF."
                    )
                if not 1 < zoom <= 10000:
                    raise ValueError("Zoom factor must be greater than 1 and no more than 10,000.")
                if not 0 <= rotation_degrees <= VIDEO_MAX_ROTATION_DEGREES:
                    raise ValueError("Rotation angle must be between 0 and 720 degrees.")
                if rotation_direction not in ("Clockwise", "Counterclockwise"):
                    raise ValueError("Choose a valid rotation direction.")
                if not (0 <= x_ratio <= 1 and 0 <= y_ratio <= 1):
                    raise ValueError("Target position percentages must be between 0 and 100.")
                settings = self.read_settings()
                if settings is None:
                    return
                _width, _height, depth, pixel_size = settings
                state = dict(self.current_fractal_view_state)
                fractal_type = self.current_fractal_type
                bilinear = bool(self.bilinear_var.get())
                rendering_mode = self.rendering_mode_var.get()
                gif_width, gif_height = gif_resolution
                filename = (
                    f"{fractal_type.lower().replace(' ', '_')}_zoom_{zoom:g}x_"
                    f"{gif_width}x{gif_height}_{duration}s_{GIF_FPS}fps.gif"
                )
                output_path = filedialog.asksaveasfilename(
                    parent=window,
                    title="Save animated fractal GIF",
                    initialfile=filename,
                    defaultextension=".gif",
                    filetypes=[("Animated GIF", "*.gif")],
                )
                if not output_path:
                    return
                window.destroy()
                self._start_fractal_animation_gif_export(
                    output_path, gif_width, gif_height, depth, pixel_size,
                    bilinear, fractal_type, state, duration, zoom,
                    x_ratio, y_ratio, rendering_mode,
                    rotation_degrees, rotation_direction,
                )
            except Exception as exc:
                messagebox.showerror("GIF animation settings", str(exc), parent=window)

        buttons = ttk.Frame(window, padding=12)
        buttons.grid(row=12, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Export GIF", command=start_gif_animation).pack(side="right", padx=4)
        ttk.Button(buttons, text="Export MP4", command=start_animation).pack(side="right", padx=4)
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right", padx=4)

    def _start_fractal_animation_gif_export(
        self, output_path, width, height, depth, pixel_size, bilinear,
        fractal_type, view_state, duration, zoom, target_x, target_y,
        rendering_mode, rotation_degrees=0, rotation_direction="Clockwise",
    ):
        self.is_exporting_animation = True
        animation_cancel_control = VideoExportControl()
        self.active_video_export_control = animation_cancel_control
        self.current_animation_format = "GIF"
        self.current_animation_gif_resolution = (int(width), int(height))
        self.current_animation_frames = int(duration) * GIF_FPS
        self.current_animation_duration = int(duration)
        self.current_animation_fps = GIF_FPS
        self._set_action_buttons()
        self.progress.configure(maximum=self.current_animation_frames, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.status_var.set(
            f"Preparing fractal GIF: {fractal_type}, {width}×{height}, "
            f"{duration}s at {GIF_FPS} FPS..."
        )
        threading.Thread(
            target=self._animation_gif_worker,
            args=(
                output_path, width, height, depth, pixel_size, bilinear,
                fractal_type, view_state, duration, zoom, target_x, target_y,
                rendering_mode, rotation_degrees, rotation_direction,
                animation_cancel_control,
            ),
            daemon=True,
        ).start()

    def _animation_gif_worker(
        self, output_path, width, height, depth, pixel_size, bilinear,
        fractal_type, view_state, duration, zoom, target_x, target_y,
        rendering_mode, rotation_degrees=0, rotation_direction="Clockwise",
        cancel_control=None,
    ):
        try:
            if cancel_control is not None:
                cancel_control.check()

            def report_progress(frame_number):
                self.animation_queue.put(("gif_progress", frame_number))

            self.animation_queue.put(("gif_status", "Preparing shared GIF color palette..."))
            result = encode_fractal_zoom_animation_gif(
                output_path, width, height, depth, fractal_type, view_state,
                duration_seconds=duration,
                zoom_factor=zoom,
                target_x=target_x,
                target_y=target_y,
                pixel_size=pixel_size,
                bilinear=bilinear,
                rendering_mode=rendering_mode,
                progress_callback=report_progress,
                rotation_degrees=rotation_degrees,
                rotation_direction=rotation_direction,
                resolution=(width, height),
                cancel_control=cancel_control,
            )
            if cancel_control is not None:
                cancel_control.check()
            self.animation_queue.put(("gif_success", output_path, result))
        except VideoExportCancelled:
            removed, cleanup_error = _remove_incomplete_video_file(output_path)
            self.animation_queue.put(("gif_cancelled", output_path, removed, cleanup_error))
        except Exception as exc:
            if cancel_control is not None and cancel_control.cancelled:
                removed, cleanup_error = _remove_incomplete_video_file(output_path)
                self.animation_queue.put(("gif_cancelled", output_path, removed, cleanup_error))
            else:
                _remove_incomplete_video_file(output_path)
                self.animation_queue.put(("gif_error", str(exc)))

    def _start_fractal_animation_export(self, output_path, width, height, depth, pixel_size, bilinear, fractal_type, view_state, duration, fps, zoom, target_x, target_y, rendering_mode, rotation_degrees=0, rotation_direction="Clockwise", video_codec=VIDEO_DEFAULT_CODEC, bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS):
        self.is_exporting_animation = True
        animation_cancel_control = VideoExportControl()
        self.active_video_export_control = animation_cancel_control
        self.current_animation_format = "MP4"
        self.current_animation_video_codec = video_codec
        self.current_animation_bitrate_kbps = int(bitrate_kbps)
        self.current_animation_frames = int(duration) * int(fps)
        self.current_animation_duration = int(duration)
        self.current_animation_fps = int(fps)
        self._set_action_buttons()
        self.progress.configure(maximum=self.current_animation_frames, value=0)
        self.progress.pack(fill="x", padx=12, pady=(0, 5))
        self.status_var.set(f"Preparing {fractal_type} zoom animation: {width}×{height}, {duration}s at {fps} FPS...")
        threading.Thread(
            target=self._animation_worker,
            args=(output_path, width, height, depth, pixel_size, bilinear, fractal_type, view_state, duration, fps, zoom, target_x, target_y, rendering_mode, rotation_degrees, rotation_direction, video_codec, bitrate_kbps, animation_cancel_control),
            daemon=True,
        ).start()

    def _animation_worker(self, output_path, width, height, depth, pixel_size, bilinear, fractal_type, view_state, duration, fps, zoom, target_x, target_y, rendering_mode, rotation_degrees=0, rotation_direction="Clockwise", video_codec=VIDEO_DEFAULT_CODEC, bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS, cancel_control=None):
        try:
            if cancel_control is not None:
                cancel_control.check()
            def report_progress(frame_number):
                self.animation_queue.put(("progress", frame_number))
            result = encode_fractal_zoom_animation(
                output_path, width, height, depth, fractal_type, view_state,
                duration_seconds=duration, fps=fps, zoom_factor=zoom,
                target_x=target_x, target_y=target_y, pixel_size=pixel_size,
                bilinear=bilinear, rendering_mode=rendering_mode,
                progress_callback=report_progress,
                rotation_degrees=rotation_degrees,
                rotation_direction=rotation_direction,
                video_codec=video_codec,
                bitrate_kbps=bitrate_kbps,
                cancel_control=cancel_control,
            )
            if cancel_control is not None:
                cancel_control.check()
            self.animation_queue.put(("success", output_path, result))
        except VideoExportCancelled:
            removed, cleanup_error = _remove_incomplete_video_file(output_path)
            self.animation_queue.put(("cancelled", output_path, removed, cleanup_error))
        except Exception as exc:
            if cancel_control is not None and cancel_control.cancelled:
                removed, cleanup_error = _remove_incomplete_video_file(output_path)
                self.animation_queue.put(("cancelled", output_path, removed, cleanup_error))
            else:
                self.animation_queue.put(("error", str(exc)))

    def _poll_animation_result(self):
        try:
            while True:
                item = self.animation_queue.get_nowait()
                if item[0] == "progress":
                    if self.active_video_export_control is not None and self.active_video_export_control.cancelled:
                        continue
                    frame_number = item[1]
                    self.progress.configure(value=frame_number)
                    self.status_var.set(f"Rendering fractal animation: frame {frame_number}/{self.current_animation_frames} ({frame_number / self.current_animation_fps:.1f}/{self.current_animation_duration}s)")
                elif item[0] == "gif_status":
                    if self.active_video_export_control is None or not self.active_video_export_control.cancelled:
                        self.status_var.set(item[1])
                elif item[0] == "gif_progress":
                    if self.active_video_export_control is not None and self.active_video_export_control.cancelled:
                        continue
                    frame_number = item[1]
                    self.progress.configure(value=frame_number)
                    self.status_var.set(
                        f"Rendering fractal GIF: frame {frame_number}/{self.current_animation_frames} "
                        f"({frame_number / GIF_FPS:.1f}/{self.current_animation_duration}s)"
                    )
                elif item[0] == "gif_success":
                    _, output_path, render_info = item
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.configure(value=self.current_animation_frames)
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    self.status_var.set(
                        f"Saved fractal animation GIF ({render_info['width']}×{render_info['height']}): {output_path}"
                    )
                    messagebox.showinfo(
                        "Fractal GIF complete",
                        f"Your {render_info['duration_seconds']}-second animated fractal GIF has been saved.\n\n"
                        f"Resolution: {render_info['width']} × {render_info['height']}\n"
                        f"Frame rate: {render_info['fps']} FPS\n"
                        f"Frames: {render_info['frames']}\n"
                        f"Fractal renderer: {render_info.get('backend', 'Renderer')}\n\n"
                        + output_path,
                    )
                elif item[0] == "gif_cancelled":
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.configure(value=0)
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    removed = item[2] if len(item) > 2 else not os.path.exists(item[1])
                    cleanup_error = item[3] if len(item) > 3 else None
                    if removed:
                        self.status_var.set("Fractal GIF export cancelled. Incomplete GIF deleted.")
                    else:
                        self.status_var.set("Fractal GIF cancelled, but the incomplete GIF could not be deleted.")
                        messagebox.showwarning(
                            "Incomplete GIF could not be deleted",
                            "The GIF export was cancelled, but Windows still has the incomplete file locked. "
                            "Close any application using it and delete it manually.\n\n"
                            f"File: {item[1]}\nReason: {cleanup_error or 'File is still in use.'}",
                        )
                elif item[0] == "gif_error":
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    self.status_var.set("Fractal GIF export failed.")
                    messagebox.showerror("Fractal GIF failed", item[1])
                elif item[0] == "success":
                    _, output_path, render_info = item
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.configure(value=self.current_animation_frames)
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    backend = render_info.get("backend", "Renderer")
                    codec_label = render_info.get("codec", video_codec_label(self.video_codec_var.get()))
                    encoder_label = render_info.get("encoder_label", f"{codec_label} encoder")
                    self.status_var.set(
                        f"Saved {codec_label} fractal animation ({backend}; {encoder_label}): {output_path}"
                    )
                    encoder_note = (
                        f"\n\nNVENC was unavailable, so the CPU encoder for {codec_label} was used:\n"
                        + str(render_info.get("encoder_fallback_reason"))
                        if render_info.get("encoder_fallback_reason") else ""
                    )
                    messagebox.showinfo(
                        "Fractal animation complete",
                        f"Your {self.current_animation_duration}-second, {self.current_animation_fps}-FPS "
                        f"{codec_label} fractal zoom animation has been saved.\n\n"
                        f"Target bitrate: {self.current_animation_bitrate_kbps // 1000} Mbit/s\n"
                        f"Fractal renderer: {backend}\nVideo encoder: {encoder_label}\n\n"
                        + output_path + encoder_note,
                    )
                elif item[0] == "cancelled":
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.configure(value=0)
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    removed = item[2] if len(item) > 2 else not os.path.exists(item[1])
                    cleanup_error = item[3] if len(item) > 3 else None
                    if removed:
                        self.status_var.set("Fractal animation cancelled. Incomplete MP4 deleted.")
                    else:
                        self.status_var.set("Fractal animation cancelled, but the incomplete MP4 could not be deleted.")
                        messagebox.showwarning(
                            "Incomplete video could not be deleted",
                            "The animation was cancelled, but Windows still has the incomplete file locked. "
                            "Close any application using it and delete it manually.\n\n"
                            f"File: {item[1]}\nReason: {cleanup_error or 'File is still in use.'}",
                        )
                elif item[0] == "error":
                    self.is_exporting_animation = False
                    self.active_video_export_control = None
                    self.progress.pack_forget()
                    self._set_action_buttons()
                    self.status_var.set("Fractal animation export failed.")
                    messagebox.showerror("Fractal animation failed", item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_animation_result)

    def _set_action_buttons(self):
        busy = (self.is_generating or self.is_exporting_video or self.is_exporting_gif
                or self.is_batch_generating or self.is_exporting_animation)
        self.generate_button.configure(state="disabled" if busy else "normal")
        self.fractal_button.configure(state="disabled" if busy else "normal")
        self.fractal_type_combo.configure(state="disabled" if busy else "readonly")
        self.rendering_mode_combo.configure(state="disabled" if busy else "readonly")
        if hasattr(self, "reset_view_button"):
            self.reset_view_button.configure(
                state="normal" if self.current_image_type == "fractal" and self.current_fractal_view_state and not busy else "disabled"
            )
        self.video_button.configure(state="disabled" if busy else "normal")
        export_active = bool(self.is_exporting_video or self.is_exporting_animation)
        if export_active:
            if not self.cancel_video_button.winfo_manager():
                self.cancel_video_button.pack(side="left", padx=6, before=self.gif_button)
            cancelling = bool(
                self.active_video_export_control is not None
                and self.active_video_export_control.cancelled
            )
            self.cancel_video_button.configure(
                text="Cancelling..." if cancelling else "Cancel Export",
                state="disabled" if cancelling else "normal",
            )
        else:
            self.cancel_video_button.pack_forget()
            self.cancel_video_button.configure(text="Cancel Export", state="disabled")
        self.video_codec_combo.configure(state="disabled" if busy else "readonly")
        self.gif_button.configure(state="disabled" if busy else "normal")
        self.duration_scale.configure(state="disabled" if busy else "normal")
        self.fps_scale.configure(state="disabled" if busy else "normal")
        self.rotation_scale.configure(state="disabled" if busy else "normal")
        self.rotation_direction_combo.configure(state="disabled" if busy else "readonly")
        self.gif_duration_scale.configure(state="disabled" if busy else "normal")
        self.gif_resolution_combo.configure(state="disabled" if busy else "readonly")
        self.resolution_combo.configure(state="disabled" if busy else "readonly")
        self.pixel_size_scale.configure(state="disabled" if busy else "normal")
        self.depth_combo.configure(state="disabled" if busy else "readonly")
        self.bilinear_check.configure(state="disabled" if busy else "normal")
        if hasattr(self, "fractal_tools_menu_button"):
            self.fractal_tools_menu_button.configure(state="disabled" if busy else "normal")
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
        left = (canvas_width - preview.width) // 2
        top = (canvas_height - preview.height) // 2
        self.preview_bounds = (left, top, preview.width, preview.height)
        self.canvas.create_image(
            left,
            top,
            image=self.preview_photo,
            anchor="nw",
            tags=("preview_image",),
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
