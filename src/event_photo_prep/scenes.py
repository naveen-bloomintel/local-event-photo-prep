from __future__ import annotations

from typing import Any


def classify_scene(metrics: dict[str, Any], metadata: dict[str, Any]) -> str:
    mean = metrics["mean_luma"]
    contrast = metrics["contrast_std"]
    iso = metadata.get("iso") or 0
    flash = metadata.get("flash_fired", False)
    if flash:
        return "flash / artificial lighting"
    subject = float(metrics.get("subject_luma", mean))
    backlight = float(metrics.get("backlight_score", 0))
    p90 = float(metrics.get("luma_p90", mean))
    if backlight >= 35 or (p90 >= 200 and subject < 110 and p90 - subject >= 70):
        return "backlit"
    if iso >= 3200 or mean < 65:
        return "low-light procession"
    if metrics.get("dynamic_range", 0) >= 175 or (
        metrics["bright_ratio"] > 0.10 and metrics["dark_ratio"] > 0.08
    ):
        return "high contrast"
    if iso >= 1600:
        return "high ISO"
    if mean < 105 and contrast < 55:
        return "warm church interior"
    if mean >= 145:
        return "outdoor daylight"
    if contrast < 42:
        return "shade"
    return "mixed church lighting"
