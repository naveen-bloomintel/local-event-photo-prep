from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _clip(value: float, low: float, high: float) -> float:
    return float(np.clip(value, low, high))


def _ev_to_target(current: float, target: float) -> float:
    return math.log2(max(target, 1.0) / max(current, 1.0))


def assess_detail(
    metrics: dict[str, Any],
    soft_face_reject_threshold: float = 55,
    soft_face_recovery_threshold: float = 72,
) -> dict[str, str]:
    """Classify detail honestly: sharpening cannot reconstruct missed focus."""
    sharpness = float(metrics.get("sharpness", 0))
    face_count = int(metrics.get("face_count", 0))
    face_sharpness = float(metrics.get("face_sharpness", sharpness))
    if face_count and face_sharpness < soft_face_reject_threshold:
        return {
            "status": "SOFT FOCUS",
            "guidance": (
                "Faces are severely out of focus. Use a sharper burst frame or reject; "
                "global sharpening cannot restore authentic facial detail."
            ),
        }
    if face_count and face_sharpness < soft_face_recovery_threshold:
        return {
            "status": "RECOVERABLE SOFTNESS",
            "guidance": "Mild face softness receives adaptive sharpening; inspect faces at 100% before printing.",
        }
    if not face_count and sharpness < 52:
        return {
            "status": "CHECK DETAIL",
            "guidance": "Low measured detail may be blur or an intentionally smooth scene; inspect at 100%.",
        }
    return {
        "status": "PRINT READY",
        "guidance": "Measured detail is suitable for the normal full-resolution Lightroom workflow.",
    }


def recommend_edits(
    metrics: dict[str, Any],
    scene: str,
    metadata: dict[str, Any] | None = None,
    enable_lens: bool = True,
    max_exposure: float = 1.25,
    max_temperature_shift: float = 900,
) -> dict[str, Any]:
    """Create an independent Lightroom recipe from one photo's tone distribution.

    Subject and face luminance are evaluated separately from bright sky and
    background so a backlit group is not darkened because daylight dominates
    the whole-frame average.
    """
    metadata = metadata or {}
    mean = float(metrics.get("mean_luma", 125))
    median = float(metrics.get("luma_p50", mean))
    subject = float(metrics.get("subject_luma", metrics.get("center_luma", mean)))
    p05 = float(metrics.get("luma_p05", max(0, mean - 45)))
    p10 = float(metrics.get("luma_p10", max(0, mean - 35)))
    p95 = float(metrics.get("luma_p95", min(255, mean + 45)))
    p99 = float(metrics.get("luma_p99", min(255, mean + 60)))
    dynamic = float(metrics.get("dynamic_range", p95 - p05))
    backlight = _clip(float(metrics.get("backlight_score", 0)) / 100, 0, 1)
    if scene == "backlit":
        backlight = max(backlight, 0.55)

    global_ev = _ev_to_target(median, 124)
    subject_ev = _ev_to_target(subject, 122)
    exposure = global_ev * (1 - 0.72 * backlight) + subject_ev * (0.72 * backlight)
    exposure += 0.16 * backlight
    if scene == "backlit":
        exposure = max(exposure, min(0.72, subject_ev * 0.78 + 0.12))

    iso = int(metadata.get("iso") or 0)
    exposure_ceiling = min(max_exposure, 0.95) if iso >= 3200 else max_exposure
    if p99 >= 252 and exposure > 0.72:
        exposure = 0.72
    exposure = round(_clip(exposure, -1.0, exposure_ceiling), 2)

    highlight_pressure = _clip((p95 - 195) / 55, 0, 1)
    highlight_pressure = max(
        highlight_pressure,
        _clip(float(metrics.get("bright_ratio", 0)) * 8, 0, 1),
    )
    highlights = -round(8 + 72 * max(highlight_pressure, backlight * 0.92))

    subject_need = _clip((118 - subject) / 78, 0, 1)
    shadow_need = _clip((58 - p10) / 53, 0, 1)
    shadows = round(8 + 52 * subject_need + 28 * backlight + 14 * shadow_need)
    shadows = int(_clip(shadows, 0, 92))

    whites = int(_clip(round(10 - 34 * highlight_pressure - 8 * backlight), -30, 14))
    if p05 < 8:
        blacks = 10
    elif p05 < 18:
        blacks = 5
    elif p05 > 42:
        blacks = -10
    elif p05 > 30:
        blacks = -6
    else:
        blacks = -2

    if dynamic > 180:
        contrast = -10
    elif dynamic > 150:
        contrast = -6
    elif dynamic < 85:
        contrast = 12
    elif dynamic < 110:
        contrast = 7
    else:
        contrast = 2
    contrast = int(_clip(contrast - 4 * backlight, -14, 14))

    sharpness_score = float(metrics.get("sharpness", 60))
    face_count = int(metrics.get("face_count", 0))
    face_sharpness = float(metrics.get("face_sharpness", sharpness_score))
    detail_score = min(sharpness_score, face_sharpness) if face_count else sharpness_score
    recoverable_softness = _clip((78 - detail_score) / 28, 0, 1)
    severe_softness = detail_score < 55
    texture = int(round(7 + 9 * recoverable_softness))
    clarity = 3 if face_count else int(round(5 + 3 * recoverable_softness))
    dehaze = 1 if scene in {"warm church interior", "low-light procession"} else 3
    colorfulness = float(metrics.get("colorfulness", 35))
    vibrance = 6 if colorfulness >= 58 else 10 if colorfulness >= 42 else 14

    # Estimate a restrained white-balance correction from low-saturation,
    # midtone pixels. Embedded RAW previews already contain the camera's WB,
    # so this corrects a visible residual cast instead of pretending to recover
    # sensor-neutral multipliers from an RGB preview.
    neutral_red = float(metrics.get("neutral_red", metrics.get("mean_red", 1)))
    neutral_green = float(metrics.get("neutral_green", metrics.get("mean_green", 1)))
    neutral_blue = float(metrics.get("neutral_blue", metrics.get("mean_blue", 1)))
    green = max(neutral_green, 1.0)
    warm_cast = (neutral_red - neutral_blue) / green
    green_cast = (neutral_green - (neutral_red + neutral_blue) / 2) / green
    correction_strength = 0.55 if scene == "warm church interior" else 0.75
    temperature_shift = _clip(
        -warm_cast * 2300 * correction_strength,
        -max_temperature_shift,
        max_temperature_shift,
    )
    temperature = int(round(_clip(5200 + temperature_shift, 2000, 9000) / 50) * 50)
    tint = int(round(_clip(green_cast * 75 * correction_strength, -30, 30)))

    if iso >= 6400:
        luminance_nr = 42
    elif iso >= 3200:
        luminance_nr = 34
    elif iso >= 1600:
        luminance_nr = 26
    elif iso >= 800:
        luminance_nr = 17
    elif iso >= 400:
        luminance_nr = 10
    else:
        luminance_nr = 4 if subject < 75 else 0
    if exposure >= 0.7:
        luminance_nr = min(45, luminance_nr + 6)

    if severe_softness:
        sharpen_amount = 58
        sharpen_detail = 20
    else:
        sharpen_amount = int(round(42 + 26 * recoverable_softness))
        sharpen_detail = int(round(24 + 12 * recoverable_softness))
    sharpen_radius = 0.8 if face_count else 1.0
    sharpen_masking = 72 if face_count else int(round(32 + 10 * recoverable_softness))
    vignette = -8 if scene in {"warm church interior", "mixed church lighting", "low-light procession"} else -5

    return {
        "Temperature": temperature,
        "Tint": tint,
        "Exposure2012": exposure,
        "Contrast2012": contrast,
        "Highlights2012": int(_clip(highlights, -85, -5)),
        "Shadows2012": shadows,
        "Whites2012": whites,
        "Blacks2012": blacks,
        "Texture": texture,
        "Clarity2012": clarity,
        "Dehaze": dehaze,
        "Vibrance": vibrance,
        "Saturation": 0,
        "Sharpness": sharpen_amount,
        "SharpenRadius": sharpen_radius,
        "SharpenDetail": sharpen_detail,
        "SharpenEdgeMasking": sharpen_masking,
        "LuminanceSmoothing": luminance_nr,
        "LuminanceNoiseReductionDetail": 50,
        "LuminanceNoiseReductionContrast": 0,
        "ColorNoiseReduction": 25,
        "ColorNoiseReductionDetail": 50,
        "ColorNoiseReductionSmoothness": 50,
        "LensProfileEnable": 1 if enable_lens else 0,
        "RemoveChromaticAberration": 1 if enable_lens else 0,
        "PostCropVignetteAmount": vignette,
        "PostCropVignetteMidpoint": 42,
        "PostCropVignetteFeather": 78,
        "PostCropVignetteRoundness": 0,
        "PostCropVignetteStyle": 1,
    }


def explain_edits(metrics: dict[str, Any], scene: str) -> str:
    subject = float(metrics.get("subject_luma", metrics.get("mean_luma", 0)))
    backlight = float(metrics.get("backlight_score", 0))
    dynamic = float(metrics.get("dynamic_range", 0))
    red = float(metrics.get("neutral_red", 0))
    green = float(metrics.get("neutral_green", 0))
    blue = float(metrics.get("neutral_blue", 0))
    parts = [f"{scene}", f"subject light {subject:.0f}/255", f"range {dynamic:.0f}"]
    if backlight >= 30:
        parts.append(f"backlight {backlight:.0f}/100")
    if metrics.get("face_count", 0):
        parts.append(f"{int(metrics['face_count'])} face(s) measured")
    if any((red, green, blue)):
        parts.append(f"neutral RGB {red:.0f}/{green:.0f}/{blue:.0f}")
    return " · ".join(parts)


def simulate_edit(image: Image.Image, edit: dict[str, Any]) -> Image.Image:
    """Approximate Adobe tone controls for the in-app preview."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    temperature = float(edit.get("Temperature", 5200))
    tint = float(edit.get("Tint", 0))
    warmth = _clip((temperature - 5200) / 3800, -0.8, 1.0)
    magenta = _clip(tint / 100, -0.3, 0.3)
    rgb[..., 0] *= 1 + 0.22 * warmth + 0.12 * magenta
    rgb[..., 1] *= 1 - 0.12 * magenta
    rgb[..., 2] *= 1 - 0.22 * warmth + 0.12 * magenta
    rgb *= 2 ** float(edit.get("Exposure2012", 0))
    luma = np.clip(0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2], 0, 1)
    shadows = float(edit.get("Shadows2012", 0)) / 100
    highlights = float(edit.get("Highlights2012", 0)) / 100
    whites = float(edit.get("Whites2012", 0)) / 100
    blacks = float(edit.get("Blacks2012", 0)) / 100
    lift = shadows * (1 - luma) ** 2 * 0.62
    compress = highlights * luma**2 * 0.48
    end_points = whites * luma**5 * 0.22 + blacks * (1 - luma) ** 5 * 0.22
    rgb = np.clip(rgb + (lift + compress + end_points)[..., None], 0, 1)
    result = Image.fromarray(np.uint8(np.round(rgb * 255)), "RGB")
    contrast = float(edit.get("Contrast2012", 0))
    result = ImageEnhance.Contrast(result).enhance(max(0.2, 1 + contrast / 100))
    vibrance = float(edit.get("Vibrance", 0)) + float(edit.get("Saturation", 0))
    result = ImageEnhance.Color(result).enhance(max(0.2, 1 + vibrance / 150))
    clarity_texture = float(edit.get("Clarity2012", 0)) + float(edit.get("Texture", 0))
    result = ImageEnhance.Sharpness(result).enhance(max(0.2, 1 + clarity_texture / 55))
    amount = int(_clip(float(edit.get("Sharpness", 40)) * 1.7, 0, 220))
    radius = _clip(float(edit.get("SharpenRadius", 1.0)), 0.5, 3.0)
    result = result.filter(ImageFilter.UnsharpMask(radius=radius, percent=amount, threshold=3))

    vignette = float(edit.get("PostCropVignetteAmount", 0))
    if vignette < 0:
        rgb = np.asarray(result, dtype=np.float32) / 255.0
        height, width = rgb.shape[:2]
        yy, xx = np.ogrid[-1:1:complex(height), -1:1:complex(width)]
        radial = np.clip((xx * xx + yy * yy - 0.16) / 1.84, 0, 1) ** 0.7
        rgb *= (1 + vignette / 100 * 0.8 * radial)[..., None]
        result = Image.fromarray(np.uint8(np.round(np.clip(rgb, 0, 1) * 255)), "RGB")
    return result
