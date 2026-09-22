from __future__ import annotations

import csv
import json
import math
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import imagehash

from .config import load_config
from .database import EventDatabase
from .edits import assess_detail, explain_edits, recommend_edits
from .metadata import extract_metadata
from .models import PhotoRecord
from .preview import fingerprint, make_preview
from .quality import analyze_quality
from .safety import assert_source_unchanged, discover_photos, validate_event_folder
from .scenes import classify_scene

ANALYSIS_VERSION = 7


def event_paths(event: Path, config: dict[str, Any]) -> dict[str, Path]:
    output = event / config["safety"]["output_folder"]
    database = output / "event-photo-prep.sqlite3"
    legacy_database = output / "churchphotoai.sqlite3"
    # Keep existing private event reviews usable after the public project rename.
    if legacy_database.exists() and not database.exists():
        database = legacy_database
    return {
        "root": output,
        "previews": output / "previews",
        "cache": output / "cache",
        "db": database,
    }


def scan_event(event: Path, output_folder: str = "_photo_ai") -> list[Path]:
    return discover_photos(validate_event_folder(event), output_folder)


def _capture_sort_key(record: PhotoRecord) -> tuple[str, str]:
    return (record.capture_time or "9999", record.relative_path)


def _seconds_between(a: PhotoRecord, b: PhotoRecord) -> float:
    if not a.capture_time or not b.capture_time:
        return 999999
    try:
        return abs((datetime.fromisoformat(a.capture_time) - datetime.fromisoformat(b.capture_time)).total_seconds())
    except ValueError:
        return 999999


def _hash_distance(left: str, right: str) -> int:
    if not left or not right:
        return 999999
    try:
        return imagehash.hex_to_hash(left) - imagehash.hex_to_hash(right)
    except (TypeError, ValueError):
        return 999999


def hash_distance(a: PhotoRecord, b: PhotoRecord) -> int:
    return _hash_distance(a.perceptual_hash, b.perceptual_hash)


def color_distance(a: PhotoRecord, b: PhotoRecord) -> float:
    return math.sqrt(
        (a.mean_red - b.mean_red) ** 2
        + (a.mean_green - b.mean_green) ** 2
        + (a.mean_blue - b.mean_blue) ** 2
    )


def is_near_duplicate(a: PhotoRecord, b: PhotoRecord, config: dict[str, Any]) -> bool:
    analysis = config["analysis"]
    same_color_family = color_distance(a, b) <= float(analysis["duplicate_color_distance"])
    perceptually_close = hash_distance(a, b) <= int(analysis["strict_duplicate_hash_distance"])
    structure_limit = int(analysis["duplicate_structure_distance"])
    structurally_close = (
        _hash_distance(a.difference_hash, b.difference_hash) <= structure_limit
        and _hash_distance(a.wavelet_hash, b.wavelet_hash) <= structure_limit
    )
    return same_color_family and (perceptually_close or structurally_close)


def _technical_rank(record: PhotoRecord) -> tuple[float, ...]:
    """Prefer recoverable detail and people quality before cosmetic exposure differences."""
    return (
        record.selection_score,
        record.people_quality_score,
        record.camera_attention_score,
        float(record.face_count),
        record.overall_score,
        record.face_sharpness,
        record.subject_sharpness,
        record.sharpness,
        record.eyes_score,
        record.highlight_quality,
        record.shadow_quality,
        record.exposure_quality,
        record.composition_score,
        record.perceptual_quality,
    )


def group_and_rank(records: list[PhotoRecord], config: dict[str, Any]) -> None:
    ordered = sorted((record for record in records if not record.error), key=_capture_sort_key)
    threshold = float(config["analysis"]["burst_seconds"])
    hash_threshold = int(config["analysis"]["duplicate_hash_distance"])
    groups: list[list[PhotoRecord]] = []
    for record in ordered:
        if not groups:
            groups.append([record])
            continue
        previous = groups[-1][-1]
        same_camera = (
            record.camera_group == previous.camera_group
            and Path(record.relative_path).parent == Path(previous.relative_path).parent
        )
        close_time = (
            same_camera
            and _seconds_between(record, previous) <= threshold
            and _seconds_between(record, groups[-1][0]) <= max(8.0, threshold * 4)
        )
        close_hash = (
            hash_distance(record, previous) <= hash_threshold
            and color_distance(record, previous) <= float(config["analysis"]["duplicate_color_distance"])
        )
        if close_time or close_hash:
            groups[-1].append(record)
        else:
            groups.append([record])

    keep_cut = float(config["analysis"]["keep_score"])
    alt_cut = float(config["analysis"]["alt_score"])
    hero_cut = float(config["analysis"]["hero_score"])
    people_weight = float(config["analysis"]["people_selection_weight"])
    soft_face_reject_threshold = float(config["analysis"]["soft_face_reject_threshold"])
    for number, group in enumerate(groups, start=1):
        for record in group:
            similar_frames = [other for other in group if is_near_duplicate(record, other, config)]
            expected_faces = max((other.face_count for other in similar_frames), default=record.face_count)
            if expected_faces:
                face_completeness = min(100.0, record.face_count / expected_faces * 100)
                record.people_quality_score = round(
                    0.30 * face_completeness
                    + 0.28 * record.eyes_score
                    + 0.18 * record.smile_score
                    + 0.24 * record.face_sharpness,
                    2,
                )
                record.camera_attention_score = round(
                    0.55 * face_completeness + 0.45 * record.eyes_score,
                    2,
                )
                record.selection_score = round(
                    (1 - people_weight) * record.overall_score
                    + people_weight * record.people_quality_score,
                    2,
                )
            else:
                record.people_quality_score = 50.0
                record.camera_attention_score = 50.0
                record.selection_score = record.overall_score
        group.sort(key=_technical_rank, reverse=True)
        group_id = f"B{number:05d}"
        distinct_representatives: list[PhotoRecord] = []
        for rank, record in enumerate(group, start=1):
            record.burst_id = group_id
            record.burst_rank = rank
            record.duplicate_of = None
            duplicate = next(
                (better for better in distinct_representatives if is_near_duplicate(record, better, config)),
                None,
            )
            if record.face_count and record.face_sharpness < soft_face_reject_threshold:
                record.ai_decision = "REJECT"
                record.ai_reason = "SOFT FOCUS"
            elif duplicate is not None:
                record.ai_decision = "REJECT"
                record.ai_reason = "DUPLICATE"
                record.duplicate_of = duplicate.filename
            elif not distinct_representatives and record.selection_score >= keep_cut:
                record.ai_decision = "KEEP"
                record.ai_reason = "BEST IN GROUP"
                distinct_representatives.append(record)
            elif record.selection_score >= keep_cut:
                record.ai_decision = "KEEP"
                record.ai_reason = "UNIQUE FRAME"
                distinct_representatives.append(record)
            elif record.selection_score >= alt_cut:
                record.ai_decision = "ALT"
                record.ai_reason = "LOWER-SCORE UNIQUE FRAME"
                distinct_representatives.append(record)
            else:
                record.ai_decision = "REJECT"
                record.ai_reason = "LOW QUALITY"
                distinct_representatives.append(record)
            record.hero = record.ai_decision == "KEEP" and record.overall_score >= hero_cut

    for number, record in enumerate((r for r in records if r.error), start=1):
        record.burst_id = f"ERROR-{number:05d}"
        record.burst_rank = 1
        record.ai_decision = "REJECT"
        record.ai_reason = "PROCESSING ERROR"
        record.duplicate_of = None
        record.hero = False

    # Bursts are time-local by design, but photographers can revisit the same
    # composition later in an event. A final event-wide pass guarantees that a
    # visually near-identical frame cannot remain in the automated KEEP set.
    representatives: list[PhotoRecord] = []
    for record in sorted((r for r in records if not r.error), key=_technical_rank, reverse=True):
        if record.ai_reason == "SOFT FOCUS":
            continue
        duplicate = next(
            (better for better in representatives if is_near_duplicate(record, better, config)),
            None,
        )
        if duplicate is None:
            representatives.append(record)
            continue
        record.ai_decision = "REJECT"
        record.ai_reason = "DUPLICATE"
        record.duplicate_of = duplicate.filename
        record.hero = False


def _write_outputs(event: Path, records: list[PhotoRecord], config: dict[str, Any]) -> dict[str, Any]:
    paths = event_paths(event, config)
    paths["root"].mkdir(parents=True, exist_ok=True)
    payload = [r.to_dict() for r in sorted(records, key=_capture_sort_key)]
    (paths["root"] / "review.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    columns = list(payload[0].keys()) if payload else ["path", "effective_decision"]
    with (paths["root"] / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in payload:
            row = dict(row)
            row["edit"] = json.dumps(row.get("edit", {}), sort_keys=True)
            writer.writerow(row)
    for decision, filename in [("KEEP", "selected.txt"), ("ALT", "alternates.txt"), ("REJECT", "rejects.txt")]:
        lines = [r.path for r in records if r.effective_decision == decision]
        (paths["root"] / filename).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    duplicates = [r.path for r in records if r.ai_reason == "DUPLICATE" and r.manual_decision is None]
    (paths["root"] / "duplicates.txt").write_text(
        "\n".join(duplicates) + ("\n" if duplicates else ""), encoding="utf-8"
    )
    summary = build_summary(records)
    (paths["root"] / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_summary(records: list[PhotoRecord]) -> dict[str, Any]:
    decisions = Counter(r.effective_decision for r in records)
    cameras = Counter(r.camera_group for r in records)
    scenes = Counter(r.scene for r in records)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_photos": len(records),
        "fuji_photos": cameras["FUJI"],
        "nikon_photos": cameras["NIKON"],
        "raw_types": dict(Counter(r.extension.upper() for r in records)),
        "burst_groups": len({r.burst_id for r in records}),
        "keep": decisions["KEEP"],
        "alt": decisions["ALT"],
        "reject": decisions["REJECT"],
        "duplicates": sum(r.ai_reason == "DUPLICATE" and r.manual_decision is None for r in records),
        "hero": sum(r.hero for r in records),
        "soft_focus": sum(r.detail_status == "SOFT FOCUS" for r in records),
        "recoverable_softness": sum(r.detail_status == "RECOVERABLE SOFTNESS" for r in records),
        "lighting_clusters": dict(scenes),
        "average_quality_score": round(sum(r.overall_score for r in records) / len(records), 2) if records else 0,
        "errors": sum(bool(r.error) for r in records),
        "error_types": dict(Counter((r.error or "").split(":", 1)[0] for r in records if r.error)),
    }


def analyze_event(
    event: str | Path,
    config_path: str | Path | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    paths = event_paths(event, config)
    paths["previews"].mkdir(parents=True, exist_ok=True)
    paths["cache"].mkdir(parents=True, exist_ok=True)
    sources = scan_event(event, config["safety"]["output_folder"])
    db = EventDatabase(paths["db"])
    records: list[PhotoRecord] = []
    try:
        for index, source in enumerate(sources, start=1):
            ident = fingerprint(source)
            cached = db.get(source, ident)
            cache_has_required_signatures = (
                bool(cached and cached.difference_hash and cached.wavelet_hash)
                and any((cached.mean_red, cached.mean_green, cached.mean_blue))
            )
            cache_is_current = bool(cached and cached.analysis_version >= ANALYSIS_VERSION)
            if (
                cached
                and cache_is_current
                and cache_has_required_signatures
                and cached.preview_path
                and Path(cached.preview_path).exists()
            ):
                records.append(cached)
                if progress:
                    progress(index, len(sources), f"Cached {source.name}")
                continue
            relative = source.relative_to(event)
            preview = paths["previews"] / f"{ident}.jpg"
            record = PhotoRecord(
                path=str(source), relative_path=str(relative), filename=source.name,
                extension=source.suffix.lower().lstrip("."), content_fingerprint=ident,
                preview_path=str(preview), analysis_version=ANALYSIS_VERSION,
                camera_group=(
                    "FUJI" if source.suffix.lower() == ".raf"
                    else "NIKON" if source.suffix.lower() == ".nef"
                    else "OTHER"
                ),
            )
            stat_before = source.stat()
            try:
                image = make_preview(
                    source, preview, int(config["preview"]["max_edge"]), int(config["preview"]["jpeg_quality"])
                )
            except Exception as error:
                record.error = f"RAW preview failed: {type(error).__name__}: {error}"
            else:
                metadata = extract_metadata(source, image)
                for key, value in metadata.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                try:
                    metrics = analyze_quality(image)
                    scene = classify_scene(metrics, metadata)
                    for key, value in metrics.items():
                        if hasattr(record, key):
                            setattr(record, key, value)
                    detail = assess_detail(
                        metrics,
                        float(config["analysis"]["soft_face_reject_threshold"]),
                        float(config["analysis"]["soft_face_recovery_threshold"]),
                    )
                    record.detail_status = detail["status"]
                    record.detail_guidance = detail["guidance"]
                    record.scene = scene
                    record.edit = recommend_edits(
                        metrics,
                        scene,
                        metadata,
                        bool(config["editing"]["enable_lens_profile"]),
                        float(config["editing"]["max_exposure"]),
                        float(config["editing"]["max_temperature_shift"]),
                    )
                    record.edit_source = "AUTO"
                    record.edit_summary = explain_edits(metrics, scene)
                    if cached is not None:
                        record.manual_decision = cached.manual_decision
                        if cached.edit_source == "MANUAL":
                            record.edit = cached.edit
                            record.edit_source = "MANUAL"
                            record.edit_summary = "Manual Lightroom adjustments preserved during reanalysis"
                except Exception as error:
                    record.error = f"Image analysis failed: {type(error).__name__}: {error}"
            assert_source_unchanged(source, stat_before.st_size, stat_before.st_mtime_ns)
            db.put(record)
            records.append(record)
            if progress:
                progress(index, len(sources), source.name)
        group_and_rank(records, config)
        db.replace_all(records)
        db.remove_missing({str(source) for source in sources})
        return _write_outputs(event, records, config)
    finally:
        db.close()


def refresh_outputs(event: str | Path, config_path: str | Path | None = None) -> dict[str, Any]:
    event = Path(event).expanduser().resolve()
    config = load_config(config_path)
    db = EventDatabase(event_paths(event, config)["db"])
    try:
        return _write_outputs(event, db.all(), config)
    finally:
        db.close()
