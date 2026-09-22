from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _camera_group(make: str, model: str, path: Path) -> str:
    combined = f"{make} {model} {path.parent.name}".lower()
    if "fuji" in combined or path.suffix.lower() == ".raf":
        return "FUJI"
    if "nikon" in combined or path.suffix.lower() == ".nef":
        return "NIKON"
    return "OTHER"


def _exiftool(path: Path) -> dict[str, Any]:
    keys = [
        "Make", "Model", "LensModel", "FocalLength", "ISO", "ShutterSpeed",
        "FNumber", "DateTimeOriginal", "ImageWidth", "ImageHeight", "Flash",
    ]
    try:
        raw = subprocess.check_output(
            ["exiftool", "-j", *(f"-{k}" for k in keys), str(path)],
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return (json.loads(raw.decode("utf-8", errors="replace")) or [{}])[0]
    except Exception:
        return {}


def _image_exif(image: Image.Image) -> dict[str, Any]:
    exif = image.getexif()
    values = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
    try:
        nested = exif.get_ifd(ExifTags.IFD.Exif)
        values.update({ExifTags.TAGS.get(k, str(k)): v for k, v in nested.items()})
    except (AttributeError, KeyError, TypeError):
        pass
    values.setdefault("ImageWidth", image.width)
    values.setdefault("ImageHeight", image.height)
    return values


def _pillow_exif(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            return _image_exif(image)
    except Exception:
        return {}


def extract_metadata(path: Path, preview: Image.Image | tuple[int, int]) -> dict[str, Any]:
    preview_size = preview.size if isinstance(preview, Image.Image) else preview
    values = _exiftool(path) or _pillow_exif(path)
    if isinstance(preview, Image.Image):
        preview_values = _image_exif(preview)
        for key, value in preview_values.items():
            values.setdefault(key, value)
    make = str(values.get("Make") or "Unknown")
    model = str(values.get("Model") or "Unknown")
    timestamp = values.get("DateTimeOriginal") or values.get("DateTime")
    if isinstance(timestamp, str):
        timestamp = timestamp.replace(":", "-", 2)
        try:
            timestamp = datetime.fromisoformat(timestamp).isoformat()
        except ValueError:
            pass
    return {
        "camera_make": make,
        "camera_model": model,
        "camera_group": _camera_group(make, model, path),
        "lens": str(values.get("LensModel") or values.get("Lens") or "Unknown"),
        "focal_length": _as_float(values.get("FocalLength")),
        "iso": int(values["ISO"]) if str(values.get("ISO", "")).isdigit() else None,
        "shutter_speed": str(values.get("ShutterSpeed") or values.get("ExposureTime") or "") or None,
        "aperture": _as_float(values.get("FNumber")),
        "capture_time": str(timestamp) if timestamp else None,
        "width": int(values.get("ImageWidth") or preview_size[0]),
        "height": int(values.get("ImageHeight") or preview_size[1]),
        "flash_fired": "fired" in str(values.get("Flash", "")).lower(),
    }
