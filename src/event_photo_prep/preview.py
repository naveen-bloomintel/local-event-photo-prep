from __future__ import annotations

import hashlib
import importlib.util
import io
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

RAW_EXTENSIONS = {".raf", ".nef", ".dng", ".arw", ".cr2", ".cr3"}
RASTER_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}
MIN_USEFUL_PREVIEW_EDGE = 480


class RawPreviewError(RuntimeError):
    """Raised after every safe RAW preview decoder has failed."""


def fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def dependency_report() -> dict[str, Any]:
    """Return decoder availability without importing optional native modules."""
    rawpy_available = importlib.util.find_spec("rawpy") is not None
    rawpy_version = None
    libraw_version = None
    rawpy_error = None
    if rawpy_available:
        try:
            import rawpy  # type: ignore

            rawpy_version = getattr(rawpy, "__version__", "unknown")
            version = getattr(rawpy, "libraw_version", None)
            if version:
                libraw_version = ".".join(str(part) for part in version)
        except Exception as error:  # pragma: no cover - native failures vary by host
            rawpy_available = False
            rawpy_error = f"{type(error).__name__}: {error}"
    exiftool = shutil.which("exiftool")
    sips = shutil.which("sips") if platform.system() == "Darwin" else None
    return {
        "rawpy_available": rawpy_available,
        "rawpy_version": rawpy_version,
        "libraw_version": libraw_version,
        "rawpy_error": rawpy_error,
        "exiftool_path": exiftool,
        "sips_path": sips,
        "raw_preview_available": bool(rawpy_available or exiftool or sips),
    }


def _validated_image(image: Image.Image, decoder: str) -> Image.Image:
    image.load()
    result = ImageOps.exif_transpose(image).convert("RGB")
    if min(result.size) < MIN_USEFUL_PREVIEW_EDGE:
        raise ValueError(
            f"{decoder} returned only {result.width}×{result.height}; "
            "the embedded image is too small for dependable culling"
        )
    return result


def _image_from_bytes(data: bytes, decoder: str) -> Image.Image:
    if not data:
        raise ValueError(f"{decoder} returned no preview data")
    with Image.open(io.BytesIO(data)) as image:
        return _validated_image(image, decoder)


def _open_with_rawpy(path: Path) -> Image.Image:
    import rawpy  # type: ignore

    errors: list[str] = []
    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return _image_from_bytes(thumb.data, "rawpy embedded JPEG")
            return _validated_image(Image.fromarray(thumb.data), "rawpy embedded bitmap")
        except Exception as error:
            errors.append(f"embedded preview: {type(error).__name__}: {error}")
        try:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,
                no_auto_bright=True,
                output_bps=8,
            )
            return _validated_image(Image.fromarray(rgb), "rawpy/LibRaw render")
        except Exception as error:
            errors.append(f"sensor render: {type(error).__name__}: {error}")
    raise RawPreviewError("; ".join(errors))


def _open_with_exiftool(path: Path, executable: str) -> Image.Image:
    errors: list[str] = []
    for tag in ("PreviewImage", "JpgFromRaw", "OtherImage", "ThumbnailImage"):
        try:
            result = subprocess.run(
                [executable, "-b", f"-{tag}", str(path)],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return _image_from_bytes(result.stdout, f"ExifTool {tag}")
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            errors.append(f"{tag}: {detail or 'not present'}")
        except Exception as error:
            errors.append(f"{tag}: {type(error).__name__}: {error}")
    raise RawPreviewError("; ".join(errors))


def _open_with_sips(path: Path, executable: str) -> Image.Image:
    with tempfile.TemporaryDirectory(prefix="event-photo-prep-preview-") as folder:
        target = Path(folder) / "preview.jpg"
        result = subprocess.run(
            [executable, "-s", "format", "jpeg", str(path), "--out", str(target)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0 or not target.exists():
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RawPreviewError(detail or f"sips exited with status {result.returncode}")
        with Image.open(target) as image:
            return _validated_image(image, "macOS ImageIO (sips)")


def _open_raw(path: Path) -> Image.Image:
    report = dependency_report()
    failures: list[str] = []
    if report["rawpy_available"]:
        try:
            return _open_with_rawpy(path)
        except Exception as error:
            failures.append(f"rawpy/LibRaw: {type(error).__name__}: {error}")
    elif report["rawpy_error"]:
        failures.append(f"rawpy import: {report['rawpy_error']}")
    else:
        failures.append("rawpy: not installed")

    if report["exiftool_path"]:
        try:
            return _open_with_exiftool(path, str(report["exiftool_path"]))
        except Exception as error:
            failures.append(f"ExifTool: {type(error).__name__}: {error}")
    else:
        failures.append("ExifTool: not installed")

    if report["sips_path"]:
        try:
            return _open_with_sips(path, str(report["sips_path"]))
        except Exception as error:
            failures.append(f"macOS ImageIO: {type(error).__name__}: {error}")

    details = " | ".join(failures)
    raise RawPreviewError(
        f"Unable to decode a useful preview from {path.name}. {details}. "
        "On macOS run ./install_macos.sh; for the strongest metadata and preview "
        "fallback also run 'brew install exiftool'."
    )


def open_photo(path: Path) -> Image.Image:
    suffix = path.suffix.lower()
    if suffix in RASTER_EXTENSIONS:
        with Image.open(path) as image:
            image.load()
            return ImageOps.exif_transpose(image).convert("RGB")
    if suffix not in RAW_EXTENSIONS:
        raise ValueError(f"Unsupported photo type: {path.suffix or '(no extension)'}")
    return _open_raw(path)


def make_preview(path: Path, destination: Path, max_edge: int, quality: int) -> Image.Image:
    image = open_photo(path)
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "JPEG", quality=quality, optimize=True)
    return image
