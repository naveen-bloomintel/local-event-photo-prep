from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PhotoRecord:
    path: str
    relative_path: str
    filename: str
    extension: str
    camera_make: str = "Unknown"
    camera_model: str = "Unknown"
    camera_group: str = "OTHER"
    lens: str = "Unknown"
    focal_length: float | None = None
    iso: int | None = None
    shutter_speed: str | None = None
    aperture: float | None = None
    capture_time: str | None = None
    width: int | None = None
    height: int | None = None
    preview_path: str | None = None
    content_fingerprint: str = ""
    analysis_version: int = 0
    perceptual_hash: str = ""
    difference_hash: str = ""
    wavelet_hash: str = ""
    mean_red: float = 0.0
    mean_green: float = 0.0
    mean_blue: float = 0.0
    luma_p05: float = 0.0
    luma_p10: float = 0.0
    luma_p50: float = 0.0
    luma_p90: float = 0.0
    luma_p95: float = 0.0
    luma_p99: float = 0.0
    center_luma: float = 0.0
    top_luma: float = 0.0
    middle_luma: float = 0.0
    bottom_luma: float = 0.0
    face_luma: float = 0.0
    subject_luma: float = 0.0
    dynamic_range: float = 0.0
    backlight_score: float = 0.0
    colorfulness: float = 0.0
    neutral_red: float = 0.0
    neutral_green: float = 0.0
    neutral_blue: float = 0.0
    sharpness: float = 0.0
    subject_sharpness: float = 0.0
    face_sharpness: float = 0.0
    motion_quality: float = 0.0
    exposure_quality: float = 0.0
    highlight_quality: float = 0.0
    shadow_quality: float = 0.0
    face_score: float = 0.0
    face_count: int = 0
    eye_count: int = 0
    smile_count: int = 0
    eyes_score: float = 0.5
    smile_score: float = 0.5
    camera_attention_score: float = 0.5
    people_quality_score: float = 0.5
    obstruction_score: float = 0.5
    composition_score: float = 0.0
    perceptual_quality: float = 0.0
    overall_score: float = 0.0
    selection_score: float = 0.0
    detail_status: str = "UNRATED"
    detail_guidance: str = ""
    scene: str = "unclassified"
    burst_id: str = ""
    burst_rank: int = 0
    ai_decision: str = "KEEP"
    ai_reason: str = "BEST IN GROUP"
    duplicate_of: str | None = None
    manual_decision: str | None = None
    hero: bool = False
    edit: dict[str, Any] = field(default_factory=dict)
    edit_source: str = "AUTO"
    edit_summary: str = ""
    error: str | None = None

    @property
    def effective_decision(self) -> str:
        return self.manual_decision or self.ai_decision

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["effective_decision"] = self.effective_decision
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PhotoRecord:
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in value.items() if k in allowed})

    def resolved_path(self) -> Path:
        return Path(self.path).expanduser().resolve()
