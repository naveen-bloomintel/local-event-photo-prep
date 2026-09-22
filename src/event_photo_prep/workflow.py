from __future__ import annotations

import filecmp
import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .database import EventDatabase
from .models import PhotoRecord
from .pipeline import event_paths, is_near_duplicate, refresh_outputs
from .preview import RAW_EXTENSIONS, fingerprint
from .xmp import write_xmp


def load_records(event: str | Path, config_path: str | Path | None = None) -> list[PhotoRecord]:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    database_path = event_paths(event, config)["db"]
    if not database_path.exists():
        return []
    db = EventDatabase(database_path, readonly=True)
    try:
        return db.all()
    finally:
        db.close()


def save_override(
    event: str | Path,
    photo_path: str,
    decision: str | None,
    config_path: str | Path | None = None,
) -> None:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    db = EventDatabase(event_paths(event, config)["db"])
    try:
        chosen = db.get(Path(photo_path))
        if chosen is None:
            raise KeyError(photo_path)
        chosen.manual_decision = decision
        db.put(chosen)
        if decision == "KEEP":
            for peer in db.all():
                if peer.path != chosen.path and not peer.error and is_near_duplicate(chosen, peer, config):
                    peer.manual_decision = "REJECT"
                    db.put(peer)
    finally:
        db.close()
    refresh_outputs(event, config_path)


def save_edit(event: str | Path, photo_path: str, edit: dict[str, Any], config_path: str | Path | None = None) -> None:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    db = EventDatabase(event_paths(event, config)["db"])
    try:
        record = db.get(Path(photo_path))
        if record is None:
            raise KeyError(photo_path)
        record.edit = edit
        record.edit_source = "MANUAL"
        record.edit_summary = "Manual Lightroom adjustments"
        db.put(record)
    finally:
        db.close()
    refresh_outputs(event, config_path)


def _selection_digest(records: list[PhotoRecord]) -> str:
    chosen = sorted((r.path, r.effective_decision, r.content_fingerprint, r.edit) for r in records)
    return hashlib.sha256(json.dumps(chosen, sort_keys=True).encode()).hexdigest()


def approve_selection(event: str | Path, config_path: str | Path | None = None) -> Path:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    records = load_records(event, config_path)
    manifest = {
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "event": str(event),
        "selection_digest": _selection_digest(records),
        "selected_count": sum(r.effective_decision == "KEEP" for r in records),
    }
    target = event_paths(event, config)["root"] / "selection_approved.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


def is_approved(event: str | Path, config_path: str | Path | None = None) -> bool:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    target = event_paths(event, config)["root"] / "selection_approved.json"
    if not target.exists():
        return False
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
        return manifest["selection_digest"] == _selection_digest(load_records(event, config_path))
    except Exception:
        return False


def _approved_keep_records(
    event: Path,
    config_path: str | Path | None,
    *,
    raw_only: bool,
) -> list[PhotoRecord]:
    if not is_approved(event, config_path):
        raise RuntimeError("Selection is not approved, or it changed after approval.")
    config = load_config(config_path)
    records = load_records(event, config_path)
    selected = [record for record in records if record.effective_decision == "KEEP" and not record.error]
    if raw_only:
        selected = [record for record in selected if Path(record.path).suffix.lower() in RAW_EXTENSIONS]
    for record in selected:
        source = Path(record.path)
        if not source.is_file():
            raise FileNotFoundError(f"Selected source is missing: {source}")
        if fingerprint(source) != record.content_fingerprint:
            raise RuntimeError(
                f"Selected source changed after analysis: {source.name}. Reanalyze and approve again."
            )
    for index, record in enumerate(selected):
        duplicate = next(
            (peer for peer in selected[index + 1 :] if is_near_duplicate(record, peer, config)),
            None,
        )
        if duplicate is not None:
            raise RuntimeError(
                f"Two near-duplicates are marked KEEP ({record.filename} and {duplicate.filename}). "
                "Choose one strongest frame and approve again."
            )
    return selected


def write_approved_xmp(event: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    selected = _approved_keep_records(event, config_path, raw_only=False)
    written: list[str] = []
    backups: list[str] = []
    for record in selected:
        target, backup = write_xmp(record, config["safety"]["xmp_backup_suffix"])
        written.append(str(target))
        if backup:
            backups.append(str(backup))
    report = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "written": written,
        "backups": backups,
    }
    out = event_paths(event, config)["root"] / "xmp_write_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def export_selected(
    event: str | Path,
    destination: str | Path,
    config_path: str | Path | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Prepare a copy-only Lightroom import folder containing KEEP RAW + generated XMP.

    XMP files are generated in the destination, so this workflow does not need to
    write sidecars beside the original photographs. Existing destination RAW files
    are reused only when their byte size matches; conflicting files are never
    overwritten.
    """
    event = Path(event).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    selected = _approved_keep_records(event, config_path, raw_only=True)
    if destination == Path(destination.anchor):
        raise ValueError("Refusing to export to a filesystem root.")
    if destination == event or destination in event.parents or event in destination.parents:
        raise ValueError("Choose a separate sibling folder outside the event folder.")
    config = load_config(config_path)
    targets: list[tuple[PhotoRecord, Path, Path]] = []
    for record in selected:
        relative = Path(record.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe relative source path: {record.relative_path}")
        source = Path(record.path)
        target = destination / relative
        if target.exists() and (
            not target.is_file()
            or target.stat().st_size != source.stat().st_size
            or not filecmp.cmp(source, target, shallow=False)
        ):
            raise FileExistsError(f"Conflicting destination file was not overwritten: {target}")
        targets.append((record, source, target))

    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    reused: list[str] = []
    sidecars: list[str] = []
    backups: list[str] = []
    manifest_items: list[dict[str, Any]] = []
    for index, (record, source, target) in enumerate(targets, start=1):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            reused.append(str(target))
        else:
            shutil.copy2(source, target)
            copied.append(str(target))
        exported_record = replace(record, path=str(target), relative_path=record.relative_path)
        xmp_target, backup = write_xmp(exported_record, config["safety"]["xmp_backup_suffix"])
        sidecars.append(str(xmp_target))
        if backup:
            backups.append(str(backup))
        manifest_items.append(
            {
                "source_relative_path": record.relative_path,
                "exported_raw": str(target.relative_to(destination)),
                "xmp": str(xmp_target.relative_to(destination)),
                "fingerprint": record.content_fingerprint,
                "selection_score": record.selection_score,
                "scene": record.scene,
                "detail_status": record.detail_status,
                "detail_guidance": record.detail_guidance,
                "edit_summary": record.edit_summary,
            }
        )
        if progress:
            progress(index, len(targets), record.filename)
    report = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "destination": str(destination),
        "selected_count": len(sidecars),
        "raw_copied": copied,
        "raw_reused": reused,
        "xmp_written": sidecars,
        "xmp_backups": backups,
        "skipped_non_raw_keep": [
            record.relative_path
            for record in load_records(event, config_path)
            if record.effective_decision == "KEEP"
            and not record.error
            and Path(record.path).suffix.lower() not in RAW_EXTENSIONS
        ],
        "selections": manifest_items,
    }
    export_manifest = destination / "event-photo-prep-export.json"
    export_manifest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["manifest"] = str(export_manifest)
    report_path = event_paths(event, config)["root"] / "lightroom_export_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
