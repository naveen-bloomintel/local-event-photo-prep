from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = {".raf", ".nef", ".dng", ".arw", ".cr2", ".cr3", ".jpg", ".jpeg", ".tif", ".tiff"}


def validate_event_folder(path: str | Path) -> Path:
    event = Path(path).expanduser().resolve()
    if not event.exists() or not event.is_dir():
        raise ValueError(f"Event folder does not exist: {event}")
    if event == Path(event.anchor):
        raise ValueError("Refusing to use a filesystem root as an event folder")
    return event


def discover_photos(event: Path, output_folder: str = "_photo_ai") -> list[Path]:
    output = event / output_folder
    return sorted(
        p.resolve()
        for p in event.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and output not in p.parents
    )


def assert_source_unchanged(path: Path, initial_size: int, initial_mtime_ns: int) -> None:
    stat = path.stat()
    if stat.st_size != initial_size or stat.st_mtime_ns != initial_mtime_ns:
        raise RuntimeError(f"Safety violation: source changed during analysis: {path}")
