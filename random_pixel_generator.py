import os
import queue
import random
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageTk


IMAGE_MAX_SIDE = 20000
IMAGE_MAX_PIXELS = 100_000_000
VIDEO_MAX_PIXELS = 8_294_400  # 3840 × 2160
VIDEO_FPS_OPTIONS = (30, 60, 120)
VIDEO_DEFAULT_FPS = 60
VIDEO_DEFAULT_SECONDS = 10
VIDEO_MIN_SECONDS = 1
VIDEO_MAX_SECONDS = 60
VIDEO_DEFAULT_BITRATE_KBPS = 200000


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
    """Create a random RGB palette; one-bit mode is exactly black and white."""
    if depth == 1:
        return [(0, 0, 0), (255, 255, 255)]
    return [
        (random.randrange(256), random.randrange(256), random.randrange(256))
        for _ in range(1 << depth)
    ]


def generate_pixelated_indices(width, height, color_count, pixel_size=1, rng=None):
    """Generate an index grid and expand each value into a square pixel block."""
    pixel_size = int(pixel_size)
    if not 1 <= pixel_size <= 8:
        raise ValueError("Pixel size must be between 1x1 and 8x8.")

    if rng is None:
        rng = np.random.default_rng()

    # Generate only one random value per logical block, then enlarge by
    # repeating rows and columns. Crop the last blocks to retain exact output
    # dimensions when width or height is not divisible by pixel_size.
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


def generate_indexed_image(width, height, depth, pixel_size=1):
    """Generate one random palette-indexed still image using NumPy."""
    palette = make_random_palette(depth)
    indices = generate_pixelated_indices(width, height, len(palette), pixel_size)

    flat_palette = [component for color in palette for component in color]
    flat_palette.extend([0] * (768 - len(flat_palette)))

    image = Image.frombytes("P", (width, height), indices.tobytes())
    image.putpalette(flat_palette)
    return image, len(palette)


def encode_random_h264_video(output_path, width, height, depth, duration_seconds=VIDEO_DEFAULT_SECONDS, fps=VIDEO_DEFAULT_FPS, timescale=1.0, bitrate_kbps=VIDEO_DEFAULT_BITRATE_KBPS, pixel_size=1, progress_callback=None):
    """
    Create an H.264 MP4 at the selected 30, 60, or 120 fps and 1–60 second duration.
    Timescale controls how quickly the random pattern changes. At 0.25x,
    one distinct random pattern is generated for each four output frames.
    Pixel size controls the square block size, from 1x1 through 8x8.
    Only one distinct frame is held in memory at a time.
    """
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
    if not 1 <= pixel_size <= 8:
        raise ValueError("Pixel size must be between 1x1 and 8x8.")
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

    if not 0.25 <= float(timescale) <= 1.0:
        raise ValueError("Video timescale must be between 0.25x and 1.00x.")
    timescale = round(float(timescale), 2)
    unique_frame_count = max(1, min(total_frames, round(total_frames * timescale)))

    palette = np.asarray(make_random_palette(depth), dtype=np.uint8)
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
        output_frame_number = 0
        for source_frame_number in range(unique_frame_count):
            # Spread repeated frames evenly across the output timeline.
            # At 0.25x, each generated pattern is repeated exactly four times.
            output_start = round(source_frame_number * total_frames / unique_frame_count)
            output_end = round((source_frame_number + 1) * total_frames / unique_frame_count)
            repeat_count = output_end - output_start

            # Generate one new pattern for this timescale step.
            indices = generate_pixelated_indices(
                width, height, len(palette), pixel_size, rng=rng
            )
            frame_bytes = palette[indices].tobytes()

            for _ in range(repeat_count):
                process.stdin.write(frame_bytes)
                output_frame_number += 1

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


class RandomPixelGenerator:
    """Fast random-pixel image and H.264 video generator."""

    def __init__(self, root):
        self.root = root
        self.root.title("Random Pixel Image & Video Generator")
        self.image = None
        self.preview_photo = None

        self.result_queue = queue.Queue()
        self.video_queue = queue.Queue()
        self.is_generating = False
        self.is_exporting_video = False

        self.width_var = tk.StringVar(value="1920")
        self.height_var = tk.StringVar(value="1080")
        self.depth_var = tk.StringVar(value="1")
        self.pixel_size_var = tk.IntVar(value=1)
        self.pixel_size_label_var = tk.StringVar(value="1×1")
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_label_var = tk.StringVar(value="1.00x")
        self.fps_index_var = tk.IntVar(value=1)  # 0=30, 1=60, 2=120 FPS
        self.fps_label_var = tk.StringVar(value=f"{VIDEO_DEFAULT_FPS} FPS")
        self.duration_var = tk.IntVar(value=VIDEO_DEFAULT_SECONDS)
        self.duration_label_var = tk.StringVar(
            value=f"{VIDEO_DEFAULT_SECONDS} seconds"
        )
        self.current_video_fps = VIDEO_DEFAULT_FPS
        self.current_video_frames = VIDEO_DEFAULT_FPS * VIDEO_DEFAULT_SECONDS
        self.current_video_duration = VIDEO_DEFAULT_SECONDS
        self.status_var = tk.StringVar(
            value="Ready — 1920 × 1080, 1-bit black and white."
        )

        controls = ttk.Frame(root, padding=12)
        controls.pack(fill="x")

        ttk.Label(controls, text="Width (X):").grid(
            row=0, column=0, padx=(0, 5), sticky="w"
        )
        ttk.Entry(controls, textvariable=self.width_var, width=10).grid(
            row=0, column=1, padx=(0, 14)
        )

        ttk.Label(controls, text="Height (Y):").grid(
            row=0, column=2, padx=(0, 5), sticky="w"
        )
        ttk.Entry(controls, textvariable=self.height_var, width=10).grid(
            row=0, column=3, padx=(0, 14)
        )

        ttk.Label(controls, text="Color depth:").grid(
            row=0, column=4, padx=(0, 5), sticky="w"
        )
        ttk.Combobox(
            controls,
            textvariable=self.depth_var,
            values=[str(bit) for bit in range(1, 9)],
            width=5,
            state="readonly",
        ).grid(row=0, column=5, padx=(0, 6))
        ttk.Label(controls, text="bits").grid(row=0, column=6)

        pixel_size_frame = ttk.Frame(root, padding=(12, 0, 12, 5))
        pixel_size_frame.pack(fill="x")
        ttk.Label(pixel_size_frame, text="Pixel doubling:").pack(side="left")
        self.pixel_size_scale = tk.Scale(
            pixel_size_frame,
            variable=self.pixel_size_var,
            from_=1,
            to=8,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=280,
            command=self._on_pixel_size_change,
        )
        self.pixel_size_scale.pack(side="left", padx=(8, 6))
        ttk.Label(pixel_size_frame, text="1×1").pack(side="left", padx=(0, 8))
        ttk.Label(
            pixel_size_frame, textvariable=self.pixel_size_label_var, width=5
        ).pack(side="left")
        ttk.Label(pixel_size_frame, text="8×8").pack(side="left", padx=(8, 0))

        buttons = ttk.Frame(root, padding=(12, 0, 12, 8))
        buttons.pack(fill="x")

        self.generate_button = ttk.Button(
            buttons, text="Generate Random Image", command=self.generate_image
        )
        self.generate_button.pack(side="left")

        self.save_button = ttk.Button(
            buttons, text="Save PNG...", command=self.save_image, state="disabled"
        )
        self.save_button.pack(side="left", padx=7)

        self.video_button = ttk.Button(
            buttons, text="Export H.264 Video...", command=self.export_video
        )
        self.video_button.pack(side="left", padx=7)

        duration_frame = ttk.Frame(root, padding=(12, 0, 12, 4))
        duration_frame.pack(fill="x")
        ttk.Label(duration_frame, text="Video duration:").pack(side="left")
        self.duration_scale = tk.Scale(
            duration_frame,
            variable=self.duration_var,
            from_=VIDEO_MIN_SECONDS,
            to=VIDEO_MAX_SECONDS,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=400,
            command=self._on_duration_change,
        )
        self.duration_scale.pack(side="left", padx=(8, 6))
        ttk.Label(duration_frame, text="1 s").pack(side="left", padx=(0, 8))
        ttk.Label(
            duration_frame, textvariable=self.duration_label_var, width=12
        ).pack(side="left")
        ttk.Label(duration_frame, text="60 s").pack(side="left", padx=(8, 0))

        fps_frame = ttk.Frame(root, padding=(12, 0, 12, 4))
        fps_frame.pack(fill="x")
        ttk.Label(fps_frame, text="Video frame rate:").pack(side="left")
        self.fps_scale = tk.Scale(
            fps_frame,
            variable=self.fps_index_var,
            from_=0,
            to=2,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            length=280,
            command=self._on_fps_change,
        )
        self.fps_scale.pack(side="left", padx=(8, 6))
        ttk.Label(fps_frame, text="30").pack(side="left", padx=(0, 8))
        ttk.Label(fps_frame, textvariable=self.fps_label_var, width=8).pack(side="left")
        ttk.Label(fps_frame, text="120").pack(side="left", padx=(8, 0))

        speed_frame = ttk.Frame(root, padding=(12, 0, 12, 6))
        speed_frame.pack(fill="x")
        ttk.Label(speed_frame, text="Video timescale:").pack(side="left")
        self.speed_scale = tk.Scale(
            speed_frame,
            variable=self.speed_var,
            from_=0.25,
            to=1.0,
            resolution=0.05,
            orient="horizontal",
            showvalue=False,
            length=280,
            command=self._on_speed_change,
        )
        self.speed_scale.pack(side="left", padx=(8, 6))
        ttk.Label(speed_frame, text="0.25x").pack(side="left", padx=(0, 8))
        ttk.Label(speed_frame, textvariable=self.speed_label_var, width=6).pack(side="left")
        ttk.Label(speed_frame, text="1.00x").pack(side="left", padx=(8, 0))

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

        self.root.update_idletasks()
        self.resize_window_to_image(1920, 1080)
        self.generate_image()

        self.root.after(60, self._poll_image_result)
        self.root.after(80, self._poll_video_result)

    def read_settings(self):
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            depth = int(self.depth_var.get())
            pixel_size = int(self.pixel_size_var.get())
            if not 1 <= pixel_size <= 8:
                raise ValueError("Pixel size must be between 1x1 and 8x8.")
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

    def _on_pixel_size_change(self, value=None):
        if value is not None:
            self.pixel_size_var.set(max(1, min(8, int(float(value)))))
        pixel_size = int(self.pixel_size_var.get())
        self.pixel_size_label_var.set(f"{pixel_size}×{pixel_size}")

    def _on_speed_change(self, _value=None):
        self.speed_label_var.set(f"{float(self.speed_var.get()):.2f}x")

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

    def resize_window_to_image(self, image_width, image_height):
        self.root.update_idletasks()
        requested_width = max(520, image_width + 32)
        requested_height = max(360, image_height + 150)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        window_width = min(requested_width, screen_width)
        window_height = min(requested_height, screen_height)
        x = max(0, (screen_width - window_width) // 2)
        y = max(0, (screen_height - window_height) // 2)

        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.minsize(min(520, screen_width), min(360, screen_height))

    def generate_image(self):
        if self.is_generating or self.is_exporting_video:
            return

        settings = self.read_settings()
        if settings is None:
            return
        width, height, depth, pixel_size = settings

        self.is_generating = True
        self._set_action_buttons()
        self.progress.pack_forget()
        self.status_var.set(
            f"Generating still image: {width} × {height}, {depth}-bit, "
            f"{pixel_size}×{pixel_size} pixel blocks..."
        )
        self.resize_window_to_image(width, height)

        threading.Thread(
            target=self._image_worker, args=settings, daemon=True
        ).start()

    def _image_worker(self, width, height, depth, pixel_size):
        try:
            image, color_count = generate_indexed_image(
                width, height, depth, pixel_size=pixel_size
            )
            self.result_queue.put(
                ("success", image, width, height, depth, pixel_size, color_count)
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
            _, self.image, width, height, depth, pixel_size, color_count = result
            self.save_button.configure(state="normal")
            self.show_preview()
            label = (
                f"{width} × {height} | {depth}-bit | {color_count} colors | "
                f"{pixel_size}×{pixel_size} pixel blocks"
            )
            if depth == 1:
                label += " (black and white)"
            self.status_var.set(label)

        self.root.after(60, self._poll_image_result)

    def export_video(self):
        if self.is_generating or self.is_exporting_video:
            return

        settings = self.read_settings()
        if settings is None:
            return
        width, height, depth, pixel_size = settings

        if width * height > VIDEO_MAX_PIXELS:
            messagebox.showerror(
                "Video resolution too large",
                "H.264 video export is limited to 8,294,400 pixels per frame "
                "(up to 3840 × 2160 / 4K). Reduce the selected width or height.",
            )
            return

        timescale = round(float(self.speed_var.get()), 2)
        duration_seconds = int(self.duration_var.get())
        fps = self._get_selected_fps()
        bitrate_kbps = VIDEO_DEFAULT_BITRATE_KBPS
        total_frames = fps * duration_seconds
        default_name = (
            f"random_pixels_{width}x{height}_{pixel_size}x{pixel_size}px_"
            f"{duration_seconds}s_{fps}fps_{timescale:.2f}x_200mbit.mp4"
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
            f"{timescale:.2f}x timescale, fixed 200 Mbit/s bitrate..."
        )

        threading.Thread(
            target=self._video_worker,
            args=(
                output_path, width, height, depth, duration_seconds,
                fps, timescale, bitrate_kbps, pixel_size
            ),
            daemon=True,
        ).start()

    def _video_worker(
        self, output_path, width, height, depth, duration_seconds,
        fps, timescale, bitrate_kbps, pixel_size
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
                timescale=timescale,
                bitrate_kbps=bitrate_kbps,
                pixel_size=pixel_size,
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
        busy = self.is_generating or self.is_exporting_video
        self.generate_button.configure(state="disabled" if busy else "normal")
        self.video_button.configure(state="disabled" if busy else "normal")
        self.speed_scale.configure(state="disabled" if busy else "normal")
        self.duration_scale.configure(state="disabled" if busy else "normal")
        self.fps_scale.configure(state="disabled" if busy else "normal")
        self.pixel_size_scale.configure(state="disabled" if busy else "normal")
        self.save_button.configure(
            state="normal" if self.image is not None else "disabled"
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
    RandomPixelGenerator(app_window)
    app_window.mainloop()
