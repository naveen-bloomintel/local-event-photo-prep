from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import imagehash
import numpy as np
from PIL import Image, ImageFilter


def _clip_score(value: float) -> float:
    return round(float(np.clip(value, 0, 100)), 2)


@lru_cache(maxsize=1)
def _opencv_available() -> bool:
    """Probe native OpenCV safely because an ABI mismatch can terminate Python."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import cv2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _laplacian_variance(gray: np.ndarray) -> float:
    if _opencv_available():
        try:
            import cv2  # type: ignore

            # OpenCV 5 on Apple Silicon rejects float32 -> CV_64F for this
            # operation. uint8 -> CV_64F is supported by OpenCV 4 and 5.
            return float(cv2.Laplacian(gray.astype(np.uint8), cv2.CV_64F).var())
        except Exception:
            # A working import does not guarantee that the wheel supports a
            # particular SIMD/type combination. The Pillow fallback keeps one
            # bad native operation from rejecting an entire event.
            pass
    image = Image.fromarray(gray.astype(np.uint8))
    edge = np.asarray(image.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    return float(edge.var())


@lru_cache(maxsize=1)
def _yunet_detector() -> Any | None:
    """Load the bundled modern face detector once per process."""
    if not _opencv_available():
        return None
    try:
        import cv2  # type: ignore

        model = Path(__file__).with_name("assets") / "face_detection_yunet_2023mar.onnx"
        if not model.is_file() or not hasattr(cv2, "FaceDetectorYN_create"):
            return None
        return cv2.FaceDetectorYN_create(str(model), "", (320, 320), 0.5, 0.3, 5000)
    except Exception:
        return None


def _detect_faces(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Detect small and mildly blurred faces, with a legacy fallback."""
    import cv2  # type: ignore

    height, width = rgb.shape[:2]
    detector = _yunet_detector()
    if detector is not None:
        try:
            detector.setInputSize((width, height))
            _, detections = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            if detections is not None:
                result = []
                for detection in detections:
                    x, y, w, h = (int(round(float(value))) for value in detection[:4])
                    x, y = max(0, x), max(0, y)
                    w, h = min(w, width - x), min(h, height - y)
                    if w >= 20 and h >= 20:
                        result.append((x, y, w, h))
                if result:
                    return result
        except Exception:
            pass

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    faces = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    ).detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def _faces_eyes_smiles(rgb: np.ndarray) -> tuple[list[tuple[int, int, int, int]], int, int]:
    if not _opencv_available():
        return [], 0, 0
    try:
        import cv2  # type: ignore

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        base = cv2.data.haarcascades
        faces = _detect_faces(rgb)
        eye_model = cv2.CascadeClassifier(base + "haarcascade_eye_tree_eyeglasses.xml")
        smile_model = cv2.CascadeClassifier(base + "haarcascade_smile.xml")
        eyes = 0
        smiles = 0
        result: list[tuple[int, int, int, int]] = []
        for x, y, w, h in faces:
            result.append((x, y, w, h))
            upper_face = gray[y : y + int(h * 0.62), x : x + w]
            lower_face = gray[y + int(h * 0.42) : y + h, x : x + w]
            detected_eyes = eye_model.detectMultiScale(
                upper_face, scaleFactor=1.1, minNeighbors=5, minSize=(8, 8)
            )
            eyes += min(2, len(detected_eyes))
            detected_smiles = smile_model.detectMultiScale(
                lower_face,
                scaleFactor=1.6,
                minNeighbors=18,
                minSize=(max(12, w // 5), max(8, h // 12)),
            )
            smiles += min(1, len(detected_smiles))
        return result, eyes, smiles
    except Exception:
        return [], 0, 0


def analyze_quality(image: Image.Image) -> dict[str, Any]:
    small = image.copy()
    small.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    rgb = np.asarray(small.convert("RGB"), dtype=np.uint8)
    mean_rgb = rgb.reshape(-1, 3).mean(axis=0)
    gray = np.asarray(small.convert("L"), dtype=np.float32)
    mean = float(gray.mean())
    std = float(gray.std())
    p05, p10, p50, p90, p95, p99 = [
        float(value) for value in np.percentile(gray, [5, 10, 50, 90, 95, 99])
    ]
    height, width = gray.shape
    center = gray[int(height * 0.22) : int(height * 0.78), int(width * 0.10) : int(width * 0.90)]
    top = gray[: max(1, int(height * 0.34))]
    middle = gray[int(height * 0.28) : max(int(height * 0.72), int(height * 0.28) + 1)]
    bottom = gray[int(height * 0.66) :]
    center_luma = float(center.mean()) if center.size else mean
    top_luma = float(top.mean()) if top.size else mean
    middle_luma = float(middle.mean()) if middle.size else mean
    bottom_luma = float(bottom.mean()) if bottom.size else mean
    sharp_raw = _laplacian_variance(gray)
    sharpness = _clip_score(18 * np.log1p(sharp_raw))
    dark_ratio = float((gray < 12).mean())
    bright_ratio = float((gray > 245).mean())
    exposure = _clip_score(100 - abs(mean - 125) * 0.62)
    highlight = _clip_score(100 - bright_ratio * 650)
    shadow = _clip_score(100 - dark_ratio * 480)
    composition = _clip_score(55 + min(std, 55) * 0.55 - (bright_ratio + dark_ratio) * 80)

    faces, eyes, smiles = _faces_eyes_smiles(rgb)
    face_score = _clip_score(min(len(faces), 5) * 13 + (18 if faces else 0))
    eyes_score = _clip_score(50 if not faces else min(100, eyes / max(1, 2 * len(faces)) * 100))
    smile_score = _clip_score(50 if not faces else min(100, smiles / max(1, len(faces)) * 100))
    face_sharpness = sharpness
    face_luma = 0.0
    if faces:
        face_vals = []
        face_lumas = []
        for x, y, w, h in faces:
            crop = gray[y : y + h, x : x + w]
            if crop.size:
                face_vals.append(_clip_score(18 * np.log1p(_laplacian_variance(crop))))
                face_lumas.append(float(crop.mean()))
        if face_vals:
            face_sharpness = float(np.mean(face_vals))
        if face_lumas:
            face_luma = float(np.mean(face_lumas))

    # Face luminance is the strongest subject signal. The center-weighted region
    # remains important for distant groups where face detection may find few faces.
    subject_luma = 0.65 * face_luma + 0.35 * center_luma if face_luma else center_luma
    dynamic_range = p95 - p05
    highlight_gap = p90 - subject_luma
    sky_gap = top_luma - middle_luma
    backlight_score = _clip_score(
        np.clip((highlight_gap - 25) / 95, 0, 1) * 65
        + np.clip((sky_gap - 12) / 75, 0, 1) * 35
    )
    channel_max = rgb.max(axis=2).astype(np.float32)
    channel_min = rgb.min(axis=2).astype(np.float32)
    colorfulness = float(np.mean(channel_max - channel_min))
    intensity = rgb.astype(np.float32).mean(axis=2)
    saturation = channel_max - channel_min
    neutral_mask = (intensity >= 35) & (intensity <= 225) & (saturation <= np.maximum(12, intensity * 0.16))
    neutral_pixels = rgb[neutral_mask]
    if len(neutral_pixels) >= 200:
        neutral_rgb = neutral_pixels.astype(np.float32).mean(axis=0)
    else:
        neutral_rgb = mean_rgb

    camera_attention = _clip_score(50 if not faces else 0.78 * eyes_score + 0.22 * face_sharpness)
    people_quality = _clip_score(
        50 if not faces else 0.38 * eyes_score + 0.24 * smile_score + 0.38 * face_sharpness
    )

    perceptual = _clip_score(0.42 * sharpness + 0.23 * exposure + 0.18 * composition + 0.17 * min(highlight, shadow))
    overall = _clip_score(
        0.25 * sharpness
        + 0.12 * face_sharpness
        + 0.16 * exposure
        + 0.10 * highlight
        + 0.07 * shadow
        + 0.10 * composition
        + 0.10 * eyes_score
        + 0.05 * smile_score
        + 0.05 * face_score
    )
    return {
        "perceptual_hash": str(imagehash.phash(small)),
        "difference_hash": str(imagehash.dhash(small)),
        "wavelet_hash": str(imagehash.whash(small)),
        "mean_red": round(float(mean_rgb[0]), 2),
        "mean_green": round(float(mean_rgb[1]), 2),
        "mean_blue": round(float(mean_rgb[2]), 2),
        "luma_p05": round(p05, 2),
        "luma_p10": round(p10, 2),
        "luma_p50": round(p50, 2),
        "luma_p90": round(p90, 2),
        "luma_p95": round(p95, 2),
        "luma_p99": round(p99, 2),
        "center_luma": round(center_luma, 2),
        "top_luma": round(top_luma, 2),
        "middle_luma": round(middle_luma, 2),
        "bottom_luma": round(bottom_luma, 2),
        "face_luma": round(face_luma, 2),
        "subject_luma": round(subject_luma, 2),
        "dynamic_range": round(dynamic_range, 2),
        "backlight_score": backlight_score,
        "colorfulness": round(colorfulness, 2),
        "neutral_red": round(float(neutral_rgb[0]), 2),
        "neutral_green": round(float(neutral_rgb[1]), 2),
        "neutral_blue": round(float(neutral_rgb[2]), 2),
        "sharpness": sharpness,
        "subject_sharpness": sharpness,
        "face_sharpness": round(face_sharpness, 2),
        "motion_quality": sharpness,
        "exposure_quality": exposure,
        "highlight_quality": highlight,
        "shadow_quality": shadow,
        "face_score": face_score,
        "face_count": len(faces),
        "eye_count": eyes,
        "smile_count": smiles,
        "eyes_score": eyes_score,
        "smile_score": smile_score,
        "camera_attention_score": camera_attention,
        "people_quality_score": people_quality,
        "obstruction_score": composition,
        "composition_score": composition,
        "perceptual_quality": perceptual,
        "overall_score": overall,
        "mean_luma": mean,
        "contrast_std": std,
        "bright_ratio": bright_ratio,
        "dark_ratio": dark_ratio,
    }
