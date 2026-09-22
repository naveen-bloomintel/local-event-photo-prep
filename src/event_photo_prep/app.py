from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st
from PIL import Image

from event_photo_prep.edits import simulate_edit
from event_photo_prep.pipeline import analyze_event, build_summary
from event_photo_prep.preview import RAW_EXTENSIONS, dependency_report
from event_photo_prep.workflow import (
    approve_selection,
    export_selected,
    is_approved,
    load_records,
    save_edit,
    save_override,
    write_approved_xmp,
)

st.set_page_config(page_title="Local Event Photo Prep", page_icon=":material/photo_camera:", layout="wide")


def cli_default_event() -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--event", default="")
    args, _ = parser.parse_known_args()
    return args.event


def typed_slider(container: Any, name: str, low: int | float, high: int | float,
                 default: Any, step: int | float, key: str) -> int | float:
    """Keep all st.slider numeric arguments the same type."""
    if any(isinstance(value, float) for value in (low, high, step)):
        low_value, high_value, step_value = float(low), float(high), float(step)
        value = max(low_value, min(high_value, float(default)))
    else:
        low_value, high_value, step_value = int(low), int(high), int(step)
        value = max(low_value, min(high_value, int(round(float(default)))))
    return container.slider(
        name,
        min_value=low_value,
        max_value=high_value,
        value=value,
        step=step_value,
        key=key,
    )


st.session_state.setdefault("event", cli_default_event())

st.title("Local Event Photo Prep", icon=":material/photo_camera:")
st.caption(
    "Local, nondestructive culling and individualized Lightroom preparation. "
    "Original photographs are never moved, renamed, deleted, or modified by the recommended export."
)

with st.expander("Complete workflow", icon=":material/checklist:"):
    st.markdown(
        """
1. Choose an event folder containing RAF, NEF, or other supported photographs.
2. Analyze the event. The app creates previews and review data only in `_photo_ai/`.
3. Review the best frame from each burst, then inspect the KEEP set and any processing errors.
4. Use **Before / after** to review or refine each photo's independent Lightroom settings.
5. Open **Finish**, approve the current decisions and edits, and explicitly approve the export.
6. Import the generated sibling folder into Lightroom Classic with **Add** and **Include subfolders**.

Changing any decision or edit invalidates approval. The Lightroom folder contains only KEEP RAW files,
matching XMP sidecars, and an export manifest.
"""
    )

decoder = dependency_report()
with st.sidebar:
    st.header("Event")
    event_text = st.text_input(
        "Event folder",
        key="event",
        placeholder="/Users/you/Pictures/Event_Name",
    ).strip()
    analyze_clicked = st.button(
        "Analyze event",
        type="primary",
        icon=":material/search:",
        width="stretch",
        disabled=not bool(event_text),
    )
    st.subheader("RAW support")
    if decoder["rawpy_available"]:
        st.badge(
            f"rawpy {decoder['rawpy_version']} · LibRaw {decoder['libraw_version']}",
            color="green",
            icon=":material/check:",
        )
    else:
        st.badge("rawpy unavailable", color="red", icon=":material/error:")
        st.caption(decoder["rawpy_error"] or "Run ./install_macos.sh to install RAW support.")
    if decoder["exiftool_path"]:
        st.badge("ExifTool available", color="green", icon=":material/check:")
    else:
        st.caption("ExifTool is optional but recommended: `brew install exiftool`")
    st.caption("Analysis never writes XMP. Final output requires approval in Finish.")

if not event_text:
    st.info("Choose an event folder in the sidebar to begin.", icon=":material/folder_open:")
    st.stop()

event = Path(event_text).expanduser()
if not event.is_dir():
    st.error(f"Event folder does not exist: {event}", icon=":material/error:")
    st.stop()
event = event.resolve()

if analyze_clicked:
    with st.status("Analyzing photographs", expanded=True) as status:
        bar = st.progress(0.0, text="Finding photographs…")

        def progress(done: int, total: int, name: str) -> None:
            bar.progress(done / max(total, 1), text=f"Analyzing {done}/{total}: {name}")

        try:
            result = analyze_event(event, progress=progress)
            bar.progress(1.0, text="Analysis complete")
            if result["errors"]:
                status.update(
                    label=f"Analysis completed with {result['errors']} photo(s) needing attention",
                    state="error",
                    expanded=True,
                )
            else:
                status.update(
                    label=f"Analyzed {result['total_photos']} photographs",
                    state="complete",
                    expanded=False,
                )
        except Exception as error:
            status.update(label="Analysis stopped", state="error", expanded=True)
            st.error(str(error), icon=":material/error:")

try:
    records = load_records(event)
except Exception as error:
    st.error(f"Could not load the event review database: {error}", icon=":material/error:")
    records = []
if not records:
    st.warning("No analyzed photographs are available yet. Click **Analyze event**.")
    st.stop()

summary = build_summary(records)
metric_values = [
    ("Photos", summary["total_photos"]),
    ("Keep", summary["keep"]),
    ("Alternates", summary["alt"]),
    ("Reject", summary["reject"]),
    ("Duplicates", summary["duplicates"]),
    ("Hero", summary["hero"]),
    ("Bursts", summary["burst_groups"]),
    ("Soft focus", summary.get("soft_focus", 0)),
    ("Recoverable softness", summary.get("recoverable_softness", 0)),
    ("Attention", summary["errors"]),
]
for start in range(0, len(metric_values), 4):
    columns = st.columns(4)
    for column, (label, value) in zip(columns, metric_values[start : start + 4], strict=False):
        column.metric(label, value, border=True)

error_records = [record for record in records if record.error]
if error_records:
    st.error(
        f"{len(error_records)} photograph(s) need attention. They are never exported. "
        "Fix the reported dependency or decoder issue, then run analysis again.",
        icon=":material/error:",
    )
    with st.expander("Processing error details", icon=":material/diagnosis:"):
        counts = Counter(record.error for record in error_records)
        for message, count in counts.most_common():
            st.markdown(f"**{count} photo(s)**")
            st.code(message or "Unknown error", language=None)

filter_columns = st.columns([1.2, 1, 1.5, 1.6, 1])
status_options = ["KEEP", "ALT", "REJECT", "ATTENTION"]
status_filter = filter_columns[0].pills(
    "Status",
    status_options,
    default=["KEEP", "ATTENTION"],
    selection_mode="multi",
)
camera_options = sorted({record.camera_group for record in records})
camera_filter = filter_columns[1].multiselect("Camera", camera_options, default=camera_options)
scene_options = sorted({record.scene for record in records})
scene_filter = filter_columns[2].multiselect("Scene", scene_options, default=scene_options)
detail_options = sorted({record.detail_status for record in records})
detail_filter = filter_columns[3].multiselect("Detail", detail_options, default=detail_options)
sort_by = filter_columns[4].selectbox(
    "Sort", ["Capture time", "Selection score", "Softest first", "Camera", "Burst"]
)


def visible_status(record: Any) -> str:
    return "ATTENTION" if record.error else record.effective_decision


filtered = [
    record
    for record in records
    if visible_status(record) in (status_filter or [])
    and record.camera_group in camera_filter
    and record.scene in scene_filter
    and record.detail_status in detail_filter
]
if sort_by == "Selection score":
    filtered.sort(key=lambda record: record.selection_score, reverse=True)
elif sort_by == "Softest first":
    filtered.sort(
        key=lambda record: (
            record.face_sharpness if record.face_count else record.sharpness,
            record.capture_time or "9999",
        )
    )
elif sort_by == "Camera":
    filtered.sort(key=lambda record: (record.camera_group, record.capture_time or "", record.filename))
elif sort_by == "Burst":
    filtered.sort(key=lambda record: (record.burst_id, record.burst_rank))
else:
    filtered.sort(key=lambda record: (record.capture_time or "9999", record.filename))

page_controls = st.columns([1, 1, 3])
page_size = page_controls[0].selectbox("Photos per page", [24, 48, 96], index=0)
page_count = max(1, (len(filtered) + page_size - 1) // page_size)
if int(st.session_state.get("review_page", 1)) > page_count:
    st.session_state["review_page"] = page_count
page = page_controls[1].number_input(
    "Page",
    min_value=1,
    max_value=int(page_count),
    step=1,
    key="review_page",
)
page_start = (int(page) - 1) * page_size
page_records = filtered[page_start : page_start + page_size]

view = st.segmented_control(
    "Workspace",
    ["Review grid", "Burst review", "Before / after", "Finish"],
    default="Review grid",
    key="workspace_view",
    width="stretch",
)

if view == "Review grid":
    st.caption(f"Showing {len(page_records)} of {len(filtered)} matching photographs.")
    if not page_records:
        st.info("No photographs match the current filters.")
    for start in range(0, len(page_records), 3):
        columns = st.columns(3)
        for column, record in zip(columns, page_records[start : start + 3], strict=False):
            with column.container(border=True):
                if record.preview_path and Path(record.preview_path).exists():
                    st.image(record.preview_path, width="stretch")
                st.markdown(f"**{record.filename}**")
                badge_color = (
                    "green"
                    if record.effective_decision == "KEEP"
                    else "orange"
                    if record.effective_decision == "ALT"
                    else "red"
                )
                st.badge(visible_status(record), color="red" if record.error else badge_color)
                st.caption(
                    f"Selection {record.selection_score:.1f} · quality {record.overall_score:.1f} · "
                    f"{record.camera_group} · {record.scene}"
                )
                if record.error:
                    st.error(record.error)
                    continue
                detail = f"{record.burst_id} · rank {record.burst_rank} · {record.ai_reason}"
                if record.duplicate_of:
                    detail += f" of {record.duplicate_of}"
                st.caption(detail)
                detail_color = (
                    "red" if record.detail_status == "SOFT FOCUS"
                    else "orange" if record.detail_status in {"RECOVERABLE SOFTNESS", "CHECK DETAIL"}
                    else "green"
                )
                st.badge(record.detail_status, color=detail_color, icon=":material/high_quality:")
                if record.face_count:
                    st.caption(
                        f"People {record.people_quality_score:.0f} · faces {record.face_count} · "
                        f"eyes {record.eyes_score:.0f} · smiles {record.smile_score:.0f} · "
                        f"face detail {record.face_sharpness:.0f}"
                    )
                choice = st.selectbox(
                    f"Decision for {record.filename}",
                    ["KEEP", "ALT", "REJECT"],
                    index=["KEEP", "ALT", "REJECT"].index(record.effective_decision),
                    key=f"grid-{record.path}",
                    label_visibility="collapsed",
                )
                if choice != record.effective_decision:
                    save_override(event, record.path, choice)
                    st.rerun()

elif view == "Burst review":
    groups: dict[str, list[Any]] = {}
    for record in records:
        if not record.error:
            groups.setdefault(record.burst_id, []).append(record)
    bursts = sorted((group_id for group_id, group in groups.items() if len(group) > 1))
    if not bursts:
        st.info("No multi-photo burst or similarity groups were found.")
    else:
        burst = st.selectbox(
            "Burst or similarity group",
            bursts,
            format_func=lambda group_id: f"{group_id} · {len(groups[group_id])} photographs",
        )
        group = sorted(groups[burst], key=lambda record: record.burst_rank)
        st.caption("Choose the strongest moment. Marking a frame KEEP automatically rejects its near-duplicates.")
        for start in range(0, len(group), 4):
            columns = st.columns(min(4, len(group[start : start + 4])))
            for column, record in zip(columns, group[start : start + 4], strict=False):
                with column.container(border=True):
                    if record.preview_path and Path(record.preview_path).exists():
                        st.image(record.preview_path, width="stretch")
                    label = (
                        "Duplicate"
                        if record.ai_reason == "DUPLICATE"
                        else "Best"
                        if record.burst_rank == 1
                        else f"Rank {record.burst_rank}"
                    )
                    st.markdown(f"**{label} · {record.filename}**")
                    st.caption(
                        f"Selection {record.selection_score:.1f} · quality {record.overall_score:.1f} · "
                        f"people {record.people_quality_score:.0f} · eyes {record.eyes_score:.0f}"
                    )
                    if st.button(
                        "Make best",
                        key=f"burst-best-{record.path}",
                        type="primary" if record.burst_rank == 1 else "secondary",
                        icon=":material/check:",
                        width="stretch",
                    ):
                        save_override(event, record.path, "KEEP")
                        st.rerun()
                    with st.container(horizontal=True):
                        if st.button("Alternate", key=f"burst-alt-{record.path}"):
                            save_override(event, record.path, "ALT")
                            st.rerun()
                        if st.button("Reject", key=f"burst-reject-{record.path}"):
                            save_override(event, record.path, "REJECT")
                            st.rerun()

elif view == "Before / after":
    editable = [
        record
        for record in records
        if not record.error and record.preview_path and Path(record.preview_path).exists()
    ]
    if not editable:
        st.info("No successfully analyzed preview is available for editing.")
    else:
        selected = st.selectbox(
            "Photograph",
            editable,
            format_func=lambda record: (
                f"{record.filename} · {record.effective_decision} · selection {record.selection_score:.1f}"
            ),
        )
        with Image.open(selected.preview_path) as preview_image:
            original = preview_image.convert("RGB")
        left, right = st.columns(2)
        left.image(original, caption="Analyzed preview", width="stretch")
        right.image(simulate_edit(original, selected.edit), caption="Lightroom edit simulation", width="stretch")
        st.caption(f"{selected.edit_source} tuning · {selected.edit_summary}")
        st.caption(
            f"Subject light {selected.subject_luma:.0f}/255 · center {selected.center_luma:.0f}/255 · "
            f"backlight {selected.backlight_score:.0f}/100 · dynamic range {selected.dynamic_range:.0f}"
        )
        if selected.detail_status == "SOFT FOCUS":
            st.error(selected.detail_guidance, icon=":material/blur_on:")
        elif selected.detail_status in {"RECOVERABLE SOFTNESS", "CHECK DETAIL"}:
            st.warning(selected.detail_guidance, icon=":material/zoom_in:")
        else:
            st.success(selected.detail_guidance, icon=":material/high_quality:")
        if selected.face_count:
            st.info(
                f"People quality {selected.people_quality_score:.0f}/100 · camera attention "
                f"{selected.camera_attention_score:.0f}/100 · {selected.face_count} face(s) · "
                f"{selected.eye_count} detected eye(s) · {selected.smile_count} detected smile(s)"
            )
        edit = dict(selected.edit)
        controls = [
            ("Temperature", 2000, 9000, 50),
            ("Tint", -30, 30, 1),
            ("Exposure2012", -1.25, 1.25, 0.05),
            ("Contrast2012", -30, 30, 1),
            ("Highlights2012", -100, 40, 1),
            ("Shadows2012", -30, 100, 1),
            ("Whites2012", -50, 50, 1),
            ("Blacks2012", -50, 50, 1),
            ("Texture", -30, 40, 1),
            ("Clarity2012", -30, 40, 1),
            ("Dehaze", -20, 30, 1),
            ("Vibrance", -30, 50, 1),
            ("Saturation", -30, 30, 1),
            ("Sharpness", 0, 100, 1),
            ("SharpenRadius", 0.5, 3.0, 0.1),
            ("SharpenDetail", 0, 100, 1),
            ("SharpenEdgeMasking", 0, 100, 1),
            ("LuminanceSmoothing", 0, 60, 1),
            ("PostCropVignetteAmount", -30, 0, 1),
        ]
        with st.form(f"edit-form-{selected.path}"):
            edit_columns = st.columns(3)
            for index, (name, low, high, step) in enumerate(controls):
                default = edit.get(name, 5200 if name == "Temperature" else 0)
                edit[name] = typed_slider(
                    edit_columns[index % 3],
                    name,
                    low,
                    high,
                    default,
                    step,
                    key=f"edit-{selected.path}-{name}",
                )
            submitted = st.form_submit_button(
                "Save manual adjustments",
                type="primary",
                icon=":material/save:",
            )
        if submitted:
            save_edit(event, selected.path, edit)
            st.success("Adjustments saved. Approve the selection again before export.")

elif view == "Finish":
    decisions = Counter(record.effective_decision for record in records if not record.error)
    raw_keeps = [
        record
        for record in records
        if record.effective_decision == "KEEP"
        and not record.error
        and Path(record.path).suffix.lower() in RAW_EXTENSIONS
    ]
    soft_keeps = [record for record in raw_keeps if record.detail_status == "SOFT FOCUS"]
    st.markdown(
        f"Current selection: **{len(raw_keeps)} KEEP RAW**, {decisions['ALT']} alternates, "
        f"{decisions['REJECT']} rejects, and {len(error_records)} needing attention."
    )
    if soft_keeps:
        st.error(
            f"{len(soft_keeps)} manually kept photograph(s) have severely soft faces. "
            "They cannot be made authentically high-definition by sharpening; replace them with a sharper burst "
            "frame or inspect at 100% before approval.",
            icon=":material/blur_on:",
        )
    approved = is_approved(event)
    if approved:
        st.badge("Selection and edits approved", color="green", icon=":material/check_circle:")
    else:
        st.badge("Approval required", color="orange", icon=":material/pending:")
    approve_confirm = st.checkbox(
        "I reviewed the KEEP set, burst winners, processing errors, and proposed edits."
    )
    if st.button(
        "Approve current selection and edits",
        type="primary",
        icon=":material/approval:",
        disabled=not approve_confirm,
    ):
        approve_selection(event)
        st.success("Approved. Any later decision or edit will invalidate this approval.")
        st.rerun()

    st.subheader("Prepare Lightroom import folder")
    st.caption(
        "Copies only KEEP RAW originals, writes one matching XMP beside each copy, and creates a manifest. "
        "The source event remains unchanged. These are full-resolution RAW files; the 1600 px app previews are "
        "for review only and do not limit print resolution."
    )
    default_destination = str(event.parent / f"{event.name}_Lightroom_KEEP")
    destination = st.text_input("Lightroom destination folder", value=default_destination)
    export_confirm = st.checkbox(
        "I approve copying the KEEP RAW files and writing generated XMP files to this destination."
    )
    if st.button(
        "Create Lightroom folder",
        type="primary",
        icon=":material/folder_copy:",
        disabled=not (approved and export_confirm and bool(raw_keeps)),
        width="stretch",
    ):
        export_bar = st.progress(0.0, text="Preparing export…")

        def export_progress(done: int, total: int, name: str) -> None:
            export_bar.progress(done / max(total, 1), text=f"Copying {done}/{total}: {name}")

        try:
            report = export_selected(event, destination, progress=export_progress)
            export_bar.progress(1.0, text="Lightroom folder ready")
            st.success(
                f"Created {report['selected_count']} RAW + XMP pair(s) in {report['destination']}. "
                f"Manifest: {report['manifest']}"
            )
        except Exception as error:
            st.error(str(error), icon=":material/error:")

    with st.expander("Advanced: write XMP beside source RAW files", icon=":material/warning:"):
        st.warning(
            "This optional workflow writes sidecars inside the source event. Existing XMP files are backed up. "
            "The separate Lightroom folder above is safer."
        )
        source_confirm = st.checkbox(
            "I explicitly approve writing or replacing XMP sidecars beside the selected source photographs."
        )
        if st.button(
            "Write source-side XMP",
            disabled=not (approved and source_confirm),
            icon=":material/edit_document:",
            width="stretch",
        ):
            try:
                report = write_approved_xmp(event)
                st.success(
                    f"Wrote {len(report['written'])} XMP sidecars and backed up "
                    f"{len(report['backups'])} existing sidecars."
                )
            except Exception as error:
                st.error(str(error), icon=":material/error:")
