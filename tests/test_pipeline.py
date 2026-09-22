from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image, ImageDraw

from event_photo_prep.config import load_config
from event_photo_prep.database import EventDatabase
from event_photo_prep.edits import assess_detail, recommend_edits
from event_photo_prep.metadata import extract_metadata
from event_photo_prep.models import PhotoRecord
from event_photo_prep.pipeline import ANALYSIS_VERSION, analyze_event, group_and_rank, scan_event
from event_photo_prep.preview import dependency_report, open_photo
from event_photo_prep.quality import analyze_quality
from event_photo_prep.scenes import classify_scene
from event_photo_prep.workflow import (
    approve_selection,
    export_selected,
    load_records,
    save_override,
    write_approved_xmp,
)


def create_event(root: Path) -> Path:
    for folder, name, color in [
        ("Fuji", "DSCF0001.jpg", (70, 100, 140)),
        ("Nikon", "DSC_0001.jpg", (120, 75, 45)),
    ]:
        image = Image.new("RGB", (640, 480), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 50, 590, 430), outline="white", width=8)
        path = root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
    return root


def create_raw_event(root: Path) -> Path:
    for folder, name, color in [
        ("Fuji", "DSCF0001.RAF", (70, 100, 140)),
        ("Nikon", "DSC_0001.NEF", (120, 75, 45)),
    ]:
        path = root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 480), color).save(path, format="JPEG")
    return root


def test_scan_and_analyze_is_nondestructive(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    originals = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in scan_event(event)}
    summary = analyze_event(event)
    assert summary["total_photos"] == 2
    assert (event / "_photo_ai" / "review.json").exists()
    for path, (content, modified) in originals.items():
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == modified


def test_manual_override_persists_and_invalidates_approval(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    record = load_records(event)[0]
    save_override(event, record.path, "KEEP")
    assert next(r for r in load_records(event) if r.path == record.path).effective_decision == "KEEP"
    approve_selection(event)
    save_override(event, record.path, "REJECT")
    try:
        write_approved_xmp(event)
    except RuntimeError as exc:
        assert "not approved" in str(exc)
    else:
        raise AssertionError("Changed selection must invalidate approval")


def test_xmp_valid_and_existing_sidecar_backed_up(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    records = load_records(event)
    for record in records:
        save_override(event, record.path, "KEEP")
    sidecar = Path(records[0].path).with_suffix(".xmp")
    sidecar.write_text("existing user edit", encoding="utf-8")
    approve_selection(event)
    report = write_approved_xmp(event)
    assert str(sidecar) in report["written"]
    assert report["backups"]
    assert Path(report["backups"][0]).read_text(encoding="utf-8") == "existing user edit"
    ET.parse(sidecar)


def test_resumable_cache(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    preview = Path(load_records(event)[0].preview_path or "")
    before = preview.stat().st_mtime_ns
    analyze_event(event)
    assert preview.stat().st_mtime_ns == before


def test_detail_analysis_invalidates_version_6_cache(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    record = load_records(event)[0]
    record.analysis_version = 6
    record.detail_status = "UNRATED"
    database = EventDatabase(event / "_photo_ai" / "event-photo-prep.sqlite3")
    try:
        database.put(record)
    finally:
        database.close()

    analyze_event(event)

    refreshed = next(item for item in load_records(event) if item.path == record.path)
    assert ANALYSIS_VERSION > 6
    assert refreshed.analysis_version == ANALYSIS_VERSION
    assert refreshed.detail_status != "UNRATED"


def test_near_duplicates_keep_only_technical_best() -> None:
    common = {
        "relative_path": "Fuji/photo.raf",
        "extension": "raf",
        "capture_time": "2026-09-01T18:30:00",
        "perceptual_hash": "8f0f0f0f0f0f0f0f",
        "mean_red": 105.0,
        "mean_green": 92.0,
        "mean_blue": 110.0,
    }
    softer = PhotoRecord(
        path="/event/Fuji/DSF3012.RAF", filename="DSF3012.RAF",
        overall_score=84.0, sharpness=72.0, subject_sharpness=72.0, **common,
    )
    finer = PhotoRecord(
        path="/event/Fuji/DSF3013.RAF", filename="DSF3013.RAF",
        overall_score=86.0, sharpness=79.0, subject_sharpness=79.0, **common,
    )
    group_and_rank([softer, finer], load_config())
    assert finer.ai_decision == "KEEP"
    assert softer.ai_decision == "REJECT"
    assert softer.ai_reason == "DUPLICATE"
    assert softer.duplicate_of == finer.filename


def test_distinct_high_quality_frame_is_also_kept() -> None:
    first = PhotoRecord(
        path="/event/a.raf", relative_path="a.raf", filename="a.raf", extension="raf",
        capture_time="2026-09-01T18:30:00", perceptual_hash="0000000000000000",
        mean_red=100, mean_green=100, mean_blue=100, overall_score=90,
    )
    distinct = PhotoRecord(
        path="/event/b.raf", relative_path="b.raf", filename="b.raf", extension="raf",
        capture_time="2026-09-01T18:30:01", perceptual_hash="ffffffffffffffff",
        mean_red=100, mean_green=100, mean_blue=100, overall_score=80,
    )
    group_and_rank([first, distinct], load_config())
    assert first.ai_decision == "KEEP"
    assert distinct.ai_decision == "KEEP"
    assert distinct.ai_reason == "UNIQUE FRAME"


def test_event_wide_duplicate_pass_rejects_matching_frames_in_separate_bursts() -> None:
    common = {
        "extension": "raf",
        "perceptual_hash": "0123456789abcdef",
        "difference_hash": "fedcba9876543210",
        "wavelet_hash": "0011223344556677",
        "mean_red": 105.0,
        "mean_green": 100.0,
        "mean_blue": 95.0,
    }
    first = PhotoRecord(
        path="/event/first.raf",
        relative_path="first.raf",
        filename="first.raf",
        capture_time="2026-09-01T18:30:00",
        overall_score=90,
        selection_score=90,
        **common,
    )
    later = PhotoRecord(
        path="/event/later.raf",
        relative_path="later.raf",
        filename="later.raf",
        capture_time="2026-09-01T19:30:00",
        overall_score=82,
        selection_score=82,
        **common,
    )
    group_and_rank([first, later], load_config())
    assert first.ai_decision == "KEEP"
    assert later.ai_decision == "REJECT"
    assert later.ai_reason == "DUPLICATE"
    assert later.duplicate_of == first.filename


def test_people_quality_can_outweigh_small_sharpness_advantage() -> None:
    common = {
        "relative_path": "group/photo.raf",
        "extension": "raf",
        "capture_time": "2026-09-01T18:30:00",
        "perceptual_hash": "1111111111111111",
        "difference_hash": "2222222222222222",
        "wavelet_hash": "3333333333333333",
        "mean_red": 110.0,
        "mean_green": 100.0,
        "mean_blue": 95.0,
    }
    sharper_but_poor_group_moment = PhotoRecord(
        path="/event/group/a.raf", filename="a.raf", overall_score=90,
        sharpness=92, face_sharpness=90, face_count=1, eye_count=0,
        smile_count=0, eyes_score=0, smile_score=0, **common,
    )
    complete_smiling_group = PhotoRecord(
        path="/event/group/b.raf", filename="b.raf", overall_score=86,
        sharpness=86, face_sharpness=80, face_count=4, eye_count=8,
        smile_count=4, eyes_score=100, smile_score=100, **common,
    )
    group_and_rank([sharper_but_poor_group_moment, complete_smiling_group], load_config())
    assert complete_smiling_group.ai_decision == "KEEP"
    assert complete_smiling_group.selection_score > sharper_but_poor_group_moment.selection_score
    assert sharper_but_poor_group_moment.ai_decision == "REJECT"
    assert sharper_but_poor_group_moment.duplicate_of == complete_smiling_group.filename


def test_severely_soft_faces_are_not_automatically_kept() -> None:
    record = PhotoRecord(
        path="/event/group/soft.raf",
        relative_path="group/soft.raf",
        filename="soft.raf",
        extension="raf",
        overall_score=78,
        sharpness=50,
        face_sharpness=48,
        face_count=4,
        eyes_score=25,
        smile_score=50,
    )
    group_and_rank([record], load_config())
    assert record.ai_decision == "REJECT"
    assert record.ai_reason == "SOFT FOCUS"


def test_detail_assessment_and_sharpening_distinguish_recoverable_softness() -> None:
    severe = assess_detail({"sharpness": 51, "face_sharpness": 49, "face_count": 3})
    recoverable_metrics = {"sharpness": 68, "face_sharpness": 64, "face_count": 3}
    crisp_metrics = {"sharpness": 88, "face_sharpness": 86, "face_count": 3}
    recoverable = assess_detail(recoverable_metrics)
    assert severe["status"] == "SOFT FOCUS"
    assert recoverable["status"] == "RECOVERABLE SOFTNESS"
    assert recommend_edits(recoverable_metrics, "warm church interior")["Sharpness"] > recommend_edits(
        crisp_metrics, "warm church interior"
    )["Sharpness"]
    assert recommend_edits(recoverable_metrics, "warm church interior")["SharpenEdgeMasking"] >= 70


def test_backlit_group_gets_subject_recovery_not_global_darkening() -> None:
    image = Image.new("RGB", (1000, 700), (225, 238, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 250, 1000, 700), fill=(72, 74, 78))
    draw.rectangle((110, 290, 890, 570), fill=(50, 54, 60))
    for x in range(140, 880, 45):
        draw.ellipse((x, 330, x + 24, 354), fill=(95, 72, 60))
        draw.rectangle((x - 4, 354, x + 28, 455), fill=(62, 68, 78))
    metrics = analyze_quality(image)
    scene = classify_scene(metrics, {"iso": 320, "flash_fired": False})
    edit = recommend_edits(metrics, scene, {"iso": 320})
    assert scene == "backlit"
    assert metrics["backlight_score"] >= 35
    assert edit["Exposure2012"] >= 0.25
    assert edit["Shadows2012"] >= 45
    assert edit["Highlights2012"] <= -40


def test_each_photo_receives_a_distinct_tone_recipe() -> None:
    dark = Image.new("RGB", (600, 400), (45, 48, 52))
    bright = Image.new("RGB", (600, 400), (220, 222, 224))
    dark_metrics = analyze_quality(dark)
    bright_metrics = analyze_quality(bright)
    dark_scene = classify_scene(dark_metrics, {"iso": 3200, "flash_fired": False})
    bright_scene = classify_scene(bright_metrics, {"iso": 200, "flash_fired": False})
    dark_edit = recommend_edits(dark_metrics, dark_scene, {"iso": 3200})
    bright_edit = recommend_edits(bright_metrics, bright_scene, {"iso": 200})
    assert dark_edit["Exposure2012"] > bright_edit["Exposure2012"]
    assert dark_edit["LuminanceSmoothing"] > bright_edit["LuminanceSmoothing"]
    assert dark_edit != bright_edit


def test_lightroom_export_copies_only_keep_raw_and_generates_xmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = create_raw_event(tmp_path / "event")
    monkeypatch.setattr(
        "event_photo_prep.preview._open_raw",
        lambda path: Image.open(path).convert("RGB"),
    )
    analyze_event(event)
    records = load_records(event)
    chosen = records[0]
    for record in records:
        save_override(event, record.path, "KEEP" if record.path == chosen.path else "REJECT")
    approve_selection(event)
    destination = tmp_path / "event_Lightroom_KEEP"
    report = export_selected(event, destination)
    exported_raw = destination / chosen.relative_path
    exported_xmp = exported_raw.with_suffix(".xmp")
    assert report["selected_count"] == 1
    assert exported_raw.read_bytes() == Path(chosen.path).read_bytes()
    assert exported_xmp.exists()
    ET.parse(exported_xmp)
    assert not Path(chosen.path).with_suffix(".xmp").exists()
    assert not (destination / records[1].relative_path).exists()
    manifest = destination / "event-photo-prep-export.json"
    assert report["manifest"] == str(manifest)
    assert manifest.exists()
    assert len(__import__("json").loads(manifest.read_text())["selections"]) == 1


def test_lightroom_export_refuses_destination_inside_event(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    approve_selection(event)
    try:
        export_selected(event, event / "copies")
    except ValueError as exc:
        assert "separate sibling" in str(exc)
    else:
        raise AssertionError("Export inside the source event must be rejected")


def test_raw_extension_identifies_camera_even_without_exiftool(tmp_path: Path) -> None:
    image = Image.new("RGB", (640, 480), (90, 100, 110))
    path = tmp_path / "unknown.RAF"
    image.save(path, format="JPEG")
    metadata = extract_metadata(path, image)
    assert metadata["camera_group"] == "FUJI"


def test_processing_error_preserves_camera_and_actionable_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = create_raw_event(tmp_path / "event")
    monkeypatch.setattr(
        "event_photo_prep.preview._open_raw",
        lambda path: Image.open(path).convert("RGB"),
    )
    monkeypatch.setattr(
        "event_photo_prep.pipeline.analyze_quality",
        lambda image: (_ for _ in ()).throw(RuntimeError("quality exploded")),
    )
    summary = analyze_event(event)
    records = load_records(event)
    assert summary["errors"] == 2
    assert {record.camera_group for record in records} == {"FUJI", "NIKON"}
    assert all(record.ai_reason == "PROCESSING ERROR" for record in records)
    assert all((record.error or "").startswith("Image analysis failed:") for record in records)


def test_recommended_xmp_contains_meaningful_lightroom_fields(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    record = load_records(event)[0]
    save_override(event, record.path, "KEEP")
    approve_selection(event)
    report = write_approved_xmp(event)
    root = ET.parse(report["written"][0]).getroot()
    ns = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    }
    description = root.find(".//rdf:Description", ns)
    assert description is not None
    for field in [
        "Temperature",
        "Tint",
        "Exposure2012",
        "Highlights2012",
        "Shadows2012",
        "Sharpness",
        "SharpenEdgeMasking",
        "PostCropVignetteAmount",
    ]:
        assert f"{{{ns['crs']}}}{field}" in description.attrib


def test_export_requires_approval(tmp_path: Path) -> None:
    event = create_event(tmp_path / "event")
    analyze_event(event)
    with pytest.raises(RuntimeError, match="not approved"):
        export_selected(event, tmp_path / "export")


def test_dependency_report_has_actionable_decoder_state() -> None:
    report = dependency_report()
    assert "rawpy_available" in report
    assert "libraw_version" in report
    assert "raw_preview_available" in report


def test_load_records_is_read_only_and_does_not_create_missing_database(tmp_path: Path) -> None:
    event = tmp_path / "empty-event"
    event.mkdir()
    assert load_records(event) == []
    assert not (event / "_photo_ai" / "event-photo-prep.sqlite3").exists()

    analyzed = create_event(tmp_path / "analyzed-event")
    analyze_event(analyzed)
    database_path = analyzed / "_photo_ai" / "event-photo-prep.sqlite3"
    db = EventDatabase(database_path, readonly=True)
    try:
        assert len(db.all()) == 2
    finally:
        db.close()


def test_existing_churchphotoai_database_remains_readable_after_rename(tmp_path: Path) -> None:
    event = create_event(tmp_path / "legacy-event")
    analyze_event(event)
    database = event / "_photo_ai" / "event-photo-prep.sqlite3"
    legacy_database = database.with_name("churchphotoai.sqlite3")
    database.rename(legacy_database)

    records = load_records(event)

    assert len(records) == 2
    assert legacy_database.exists()
    assert not database.exists()


def test_raw_preview_failure_lists_all_available_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "broken.RAF"
    path.write_bytes(b"not a raw file")
    monkeypatch.setattr(
        "event_photo_prep.preview.dependency_report",
        lambda: {
            "rawpy_available": True,
            "rawpy_error": None,
            "exiftool_path": "/fake/exiftool",
            "sips_path": "/fake/sips",
        },
    )
    monkeypatch.setattr(
        "event_photo_prep.preview._open_with_rawpy",
        lambda path: (_ for _ in ()).throw(RuntimeError("rawpy failed")),
    )
    monkeypatch.setattr(
        "event_photo_prep.preview._open_with_exiftool",
        lambda path, executable: (_ for _ in ()).throw(RuntimeError("exiftool failed")),
    )
    monkeypatch.setattr(
        "event_photo_prep.preview._open_with_sips",
        lambda path, executable: (_ for _ in ()).throw(RuntimeError("sips failed")),
    )
    with pytest.raises(RuntimeError) as exc_info:
        open_photo(path)
    message = str(exc_info.value)
    assert "rawpy failed" in message
    assert "exiftool failed" in message
    assert "sips failed" in message
