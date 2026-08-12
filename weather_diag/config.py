from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.getenv("WEATHER_DIAG_CONFIG_DIR", PROJECT_ROOT / "configs"))
DATA_DIR = Path(os.getenv("WEATHER_DIAG_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PRODUCTS_DIR = DATA_DIR / "products"
JOBS_DIR = DATA_DIR / "jobs"
ADMIN_DIR = DATA_DIR / "admin"
THRESHOLD_MATRIX_PATH = ADMIN_DIR / "threshold_matrix.json"


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_DIR.mkdir(parents=True, exist_ok=True)


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = CONFIG_DIR / p
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_model_config(model: str) -> Dict[str, Any]:
    cfg = load_yaml(CONFIG_DIR / "models" / f"{model}.yaml")
    if not cfg:
        raise FileNotFoundError(f"Model config not found: {model}")
    return cfg


def load_thresholds() -> Dict[str, Any]:
    thresholds = load_yaml("thresholds.yaml")
    try:
        # Local import avoids a module-import cycle: the governance extension
        # uses ADMIN_DIR from this module, while runtime feature algorithms call
        # load_thresholds() only after config.py has been initialized.
        from weather_diag.diagnosis.weather_system_governance import apply_governance_thresholds

        return apply_governance_thresholds(thresholds)
    except Exception:
        # A malformed optional governance extension must not prevent the core
        # diagnostic service from starting; the admin API reports the detailed
        # matrix error while runtime falls back to repository YAML defaults.
        return thresholds


def load_layers() -> Dict[str, Any]:
    return load_yaml("layers.yaml").get("layers", {})
