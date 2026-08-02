"""
video_convert.py

Converts a landscape (16:9) video into a vertical 9:16 video suitable for
YouTube Shorts, using a blurred/zoomed copy of the same footage as the
background (fills the whole frame, no black bars top/bottom).

Requires `ffmpeg` and `ffprobe` to be on PATH.
"""

import logging
import os
import subprocess

logger = logging.getLogger("video_convert")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


def get_dimensions(path: str):
    """Returns (width, height) of the first video stream, or None if it
    can't be determined."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                path,
            ],
            capture_output=True, text=True, check=True,
        )
        width_str, height_str = result.stdout.strip().split("x")
        return int(width_str), int(height_str)
    except Exception as e:
        logger.warning("Could not probe dimensions for %s: %s", path, e)
        return None


def is_vertical(path: str) -> bool:
    """True if the video is already vertical or square (height >= width)."""
    dims = get_dimensions(path)
    if dims is None:
        # Can't tell -- assume it needs conversion rather than risk
        # uploading something that won't qualify as a Short.
        return False
    width, height = dims
    return height >= width


def convert_to_vertical(input_path: str, output_path: str) -> str:
    """
    Converts input_path (any aspect ratio) into a 1080x1920 vertical video
    at output_path: the original footage is centered over a blurred, zoomed
    copy of itself as the background. Returns output_path.
    Raises subprocess.CalledProcessError if ffmpeg fails.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    filter_complex = (
        f"[0:v]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=20:5[bg];"
        f"[0:v]scale={TARGET_WIDTH}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("Converting to vertical: %s -> %s", input_path, output_path)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg failed on %s:\n%s", input_path, e.stderr[-2000:] if e.stderr else "")
        raise

    return output_path


def ensure_vertical(input_path: str, work_dir: str) -> str:
    """
    Returns a path to a version of input_path guaranteed to be vertical
    (9:16-ish). If input_path is already vertical/square, returns it
    unchanged. Otherwise converts it into work_dir and returns the new path.
    """
    if is_vertical(input_path):
        logger.info("%s is already vertical, uploading as-is.", input_path)
        return input_path

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    converted_path = os.path.join(work_dir, f"{base_name}_vertical.mp4")
    return convert_to_vertical(input_path, converted_path)
