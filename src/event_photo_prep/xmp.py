from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import PhotoRecord

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

EDIT_RANGES: dict[str, tuple[float, float]] = {
    "Temperature": (2000, 50000),
    "Tint": (-150, 150),
    "Exposure2012": (-5, 5),
    "Contrast2012": (-100, 100),
    "Highlights2012": (-100, 100),
    "Shadows2012": (-100, 100),
    "Whites2012": (-100, 100),
    "Blacks2012": (-100, 100),
    "Texture": (-100, 100),
    "Clarity2012": (-100, 100),
    "Dehaze": (-100, 100),
    "Vibrance": (-100, 100),
    "Saturation": (-100, 100),
    "Sharpness": (0, 150),
    "SharpenRadius": (0.5, 3.0),
    "SharpenDetail": (0, 100),
    "SharpenEdgeMasking": (0, 100),
    "LuminanceSmoothing": (0, 100),
    "LuminanceNoiseReductionDetail": (0, 100),
    "LuminanceNoiseReductionContrast": (0, 100),
    "ColorNoiseReduction": (0, 100),
    "ColorNoiseReductionDetail": (0, 100),
    "ColorNoiseReductionSmoothness": (0, 100),
    "LensProfileEnable": (0, 1),
    "RemoveChromaticAberration": (0, 1),
    "PostCropVignetteAmount": (-100, 100),
    "PostCropVignetteMidpoint": (0, 100),
    "PostCropVignetteFeather": (0, 100),
    "PostCropVignetteRoundness": (-100, 100),
    "PostCropVignetteStyle": (1, 3),
}


def sidecar_path(source: Path) -> Path:
    return source.with_suffix(".xmp")


def build_xmp(record: PhotoRecord) -> bytes:
    root = ET.Element(f"{{{NS['x']}}}xmpmeta")
    rdf = ET.SubElement(root, f"{{{NS['rdf']}}}RDF")
    attrs = {
        f"{{{NS['rdf']}}}about": "",
        f"{{{NS['crs']}}}Version": "16.0",
        f"{{{NS['crs']}}}ProcessVersion": "15.4",
        f"{{{NS['crs']}}}HasSettings": "True",
        f"{{{NS['crs']}}}HasCrop": "False",
        f"{{{NS['crs']}}}WhiteBalance": "As Shot" if not record.edit.get("Temperature") else "Custom",
        f"{{{NS['crs']}}}AlreadyApplied": "False",
    }
    for key, value in record.edit.items():
        if key not in EDIT_RANGES or value is None:
            continue
        numeric = float(value)
        low, high = EDIT_RANGES[key]
        if not low <= numeric <= high:
            raise ValueError(f"Lightroom value {key}={value} is outside {low}…{high}")
        if key == "Exposure2012":
            rendered = f"{numeric:+.2f}"
        elif isinstance(value, float) and not numeric.is_integer():
            rendered = f"{numeric:.2f}".rstrip("0").rstrip(".")
        else:
            rendered = str(int(numeric))
        attrs[f"{{{NS['crs']}}}{key}"] = rendered
    desc = ET.SubElement(rdf, f"{{{NS['rdf']}}}Description", attrs)
    label = ET.SubElement(desc, f"{{{NS['dc']}}}description")
    alt = ET.SubElement(label, f"{{{NS['rdf']}}}Alt")
    li = ET.SubElement(alt, f"{{{NS['rdf']}}}li", {"{http://www.w3.org/XML/1998/namespace}lang": "x-default"})
    li.text = f"Local Event Photo Prep {record.effective_decision}; score {record.overall_score:.1f}"
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        + xml
        + b'\n<?xpacket end="w"?>\n'
    )


def validate_xmp(data: bytes) -> None:
    root = ET.fromstring(data)
    if not root.tag.endswith("xmpmeta"):
        raise ValueError("Generated document is not Adobe XMP")
    description = root.find(f".//{{{NS['rdf']}}}Description")
    if description is None:
        raise ValueError("Generated XMP has no RDF description")
    required = ("Version", "ProcessVersion", "HasSettings")
    missing = [name for name in required if f"{{{NS['crs']}}}{name}" not in description.attrib]
    if missing:
        raise ValueError(f"Generated XMP is missing Camera Raw fields: {', '.join(missing)}")


def write_xmp(record: PhotoRecord, backup_suffix: str = ".event-photo-prep-backup") -> tuple[Path, Path | None]:
    source = record.resolved_path()
    if not source.is_file():
        raise FileNotFoundError(source)
    target = sidecar_path(source)
    data = build_xmp(record)
    validate_xmp(data)
    backup: Path | None = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = Path(str(target) + backup_suffix)
        if backup.exists():
            backup = Path(str(target) + backup_suffix + f".{stamp}")
        shutil.copy2(target, backup)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target, backup
