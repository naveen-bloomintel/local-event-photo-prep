from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "preview": {"max_edge": 1600, "jpeg_quality": 88},
    "analysis": {
        "burst_seconds": 2.5,
        "duplicate_hash_distance": 10,
        "strict_duplicate_hash_distance": 10,
        "duplicate_structure_distance": 8,
        "duplicate_color_distance": 65,
        "keep_score": 62,
        "alt_score": 47,
        "hero_score": 82,
        "people_selection_weight": 0.45,
        "soft_face_reject_threshold": 55,
        "soft_face_recovery_threshold": 72,
        "workers": 0,
    },
    "editing": {
        "max_exposure": 1.25,
        "max_temperature_shift": 900,
        "enable_lens_profile": True,
    },
    "safety": {
        "output_folder": "_photo_ai",
        "xmp_backup_suffix": ".event-photo-prep-backup",
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    candidate = Path(path).expanduser() if path else Path.cwd() / "config.yaml"
    if candidate.exists():
        with candidate.open("r", encoding="utf-8") as handle:
            _merge(config, yaml.safe_load(handle) or {})
    return config
