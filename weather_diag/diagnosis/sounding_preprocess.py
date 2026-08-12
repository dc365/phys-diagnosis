from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from weather_diag.config import ADMIN_DIR, PROJECT_ROOT, ensure_dirs


DEFAULT_SOUNDING_DATA_DIR = PROJECT_ROOT / "test_datas" / "regional_radiosonde_5N55N_50E160E_20260624_20260625"
PREPROCESS_DIR = ADMIN_DIR / "sounding_preprocess"
REPORT_DIR = PREPROCESS_DIR / "reports"
CLEANED_DIR = PREPROCESS_DIR / "cleaned"
STATE_PATH = PREPROCESS_DIR / "state.json"
PREPROCESS_VERSION = "sounding-preprocess-v1"
_AUTO_PREPROCESS_THREAD: threading.Thread | None = None

STANDARD_LEVELS_HPA = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]
REQUIRED_COLUMNS = [
    "station_id",
    "station_lat",
    "station_lon",
    "requested_level",
    "pressure_hpa",
    "temperature_c",
    "dew_point_temperature_c",
    "geopotential_height_m",
    "wind_direction_degree",
    "wind_speed_m_s",
]
NUMERIC_COLUMNS = [
    "station_lat",
    "station_lon",
    "pressure_hpa",
    "temperature_c",
    "dew_point_temperature_c",
    "geopotential_height_m",
    "wind_direction_degree",
    "wind_speed_m_s",
]
OPTIONAL_TEXT_COLUMNS = ["station_name", "request_datetime_bjt", "observation_time"]

COLUMN_ALIASES = {
    "id": "station_id",
    "station": "station_id",
    "lat": "station_lat",
    "latitude": "station_lat",
    "lon": "station_lon",
    "longitude": "station_lon",
    "level": "requested_level",
    "pressure": "pressure_hpa",
    "temperature": "temperature_c",
    "temp": "temperature_c",
    "dewpoint": "dew_point_temperature_c",
    "dew_point": "dew_point_temperature_c",
    "height": "geopotential_height_m",
    "geopotential_height": "geopotential_height_m",
    "wind_dir": "wind_direction_degree",
    "wind_direction": "wind_direction_degree",
    "wind_speed": "wind_speed_m_s",
    "time": "request_datetime_bjt",
    "datetime": "request_datetime_bjt",
}


@dataclass(frozen=True)
class SoundingPreprocessConfig:
    lat_min: float = -90.0
    lat_max: float = 90.0
    lon_min: float = -180.0
    lon_max: float = 360.0
    pressure_min_hpa: float = 50.0
    pressure_max_hpa: float = 1100.0
    temperature_min_c: float = -100.0
    temperature_max_c: float = 60.0
    dewpoint_min_c: float = -120.0
    dewpoint_max_c: float = 50.0
    dewpoint_exceeds_temperature_tolerance_c: float = 0.8
    height_min_m: float = -500.0
    height_max_m: float = 35000.0
    wind_speed_min_ms: float = 0.0
    wind_speed_max_ms: float = 150.0
    z500_min_m: float = 5200.0
    z500_max_m: float = 6100.0
    z500_buddy_min_abs_m: float = 180.0
    z500_buddy_mad_factor: float = 4.5
    min_profile_levels: int = 4


class SoundingPreprocessError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_datetime(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return text
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
    if numeric > 100_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, timezone.utc).isoformat()


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def discover_sounding_csvs(root: str | Path | None = None) -> list[Path]:
    base = _resolve_path(root or DEFAULT_SOUNDING_DATA_DIR)
    if base.is_file() and base.suffix.lower() == ".csv":
        return [base]
    if not base.exists():
        return []
    return sorted(
        path for path in base.glob("*.csv")
        if path.is_file() and ".clean" not in path.name and not path.name.startswith("~")
    )


def _normalize_column_name(name: str) -> str:
    normalized = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return COLUMN_ALIASES.get(normalized, normalized)


def _normalize_requested_level(value: Any, pressure_hpa: Any = None) -> str:
    text = str(value or "").strip()
    if text.lower().endswith("hpa"):
        numeric = text[:-3]
    else:
        numeric = text
    try:
        level = int(round(float(numeric)))
    except (TypeError, ValueError):
        try:
            level = int(round(float(pressure_hpa)))
        except (TypeError, ValueError):
            return text or "unknown"
    return f"{level}hPa"


def _standardize_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns={column: _normalize_column_name(column) for column in raw.columns}).copy()
    for column in REQUIRED_COLUMNS:
        if column not in df.columns:
            df[column] = np.nan
    for column in OPTIONAL_TEXT_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df["source_row"] = np.arange(len(df), dtype=int)
    df["station_id"] = df["station_id"].astype(str).str.strip()
    df["station_id"] = df["station_id"].replace({"": np.nan, "nan": np.nan, "None": np.nan})
    df["station_name"] = df["station_name"].astype(str).str.strip().replace({"nan": ""})
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["requested_level"] = [
        _normalize_requested_level(level, pressure)
        for level, pressure in zip(df["requested_level"], df["pressure_hpa"])
    ]
    time_source = df["request_datetime_bjt"] if "request_datetime_bjt" in df.columns else df.get("observation_time", "")
    df["observation_time"] = pd.to_datetime(time_source, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
    return df


def _flag(mask: pd.Series | np.ndarray, name: str, flags: list[list[str]]) -> None:
    values = np.asarray(mask, dtype=bool)
    for index, active in enumerate(values):
        if active:
            flags[index].append(name)


def _fit_background_residuals(frame: pd.DataFrame, value_column: str) -> pd.Series:
    rows = frame[["station_lon", "station_lat", value_column]].dropna()
    residual = pd.Series(np.nan, index=frame.index, dtype=float)
    if len(rows) < 8:
        return residual
    lon = rows["station_lon"].to_numpy(dtype=float)
    lat = rows["station_lat"].to_numpy(dtype=float)
    x = (lon - np.nanmean(lon)) / max(np.nanstd(lon), 1.0)
    y = (lat - np.nanmean(lat)) / max(np.nanstd(lat), 1.0)
    design = np.column_stack([np.ones_like(x), x, y, x * y, x**2, y**2])
    values = rows[value_column].to_numpy(dtype=float)
    try:
        coef, *_ = np.linalg.lstsq(design, values, rcond=None)
        fitted = design @ coef
    except Exception:
        return residual
    residual.loc[rows.index] = values - fitted
    return residual


def _add_qc_flags(df: pd.DataFrame, config: SoundingPreprocessConfig) -> tuple[pd.DataFrame, dict[str, int]]:
    flags: list[list[str]] = [[] for _ in range(len(df))]
    _flag(df["station_id"].isna(), "missing_station_id", flags)
    _flag(df["station_lat"].isna() | ~df["station_lat"].between(config.lat_min, config.lat_max), "bad_station_lat", flags)
    _flag(df["station_lon"].isna() | ~df["station_lon"].between(config.lon_min, config.lon_max), "bad_station_lon", flags)
    _flag(df["pressure_hpa"].isna() | ~df["pressure_hpa"].between(config.pressure_min_hpa, config.pressure_max_hpa), "bad_pressure", flags)
    _flag(df["temperature_c"].isna() | ~df["temperature_c"].between(config.temperature_min_c, config.temperature_max_c), "bad_temperature", flags)
    _flag(df["dew_point_temperature_c"].isna() | ~df["dew_point_temperature_c"].between(config.dewpoint_min_c, config.dewpoint_max_c), "bad_dewpoint", flags)
    _flag(df["dew_point_temperature_c"] > df["temperature_c"] + config.dewpoint_exceeds_temperature_tolerance_c, "dewpoint_exceeds_temperature", flags)
    _flag(df["geopotential_height_m"].isna() | ~df["geopotential_height_m"].between(config.height_min_m, config.height_max_m), "bad_height", flags)
    _flag(~df["wind_direction_degree"].isna() & ~df["wind_direction_degree"].between(0.0, 360.0), "bad_wind_direction", flags)
    _flag(~df["wind_speed_m_s"].isna() & ~df["wind_speed_m_s"].between(config.wind_speed_min_ms, config.wind_speed_max_ms), "bad_wind_speed", flags)

    z500_mask = df["requested_level"].astype(str).eq("500hPa")
    _flag(z500_mask & ~df["geopotential_height_m"].between(config.z500_min_m, config.z500_max_m), "z500_height_out_of_range", flags)
    z500 = df[z500_mask].copy()
    if len(z500) >= 8:
        residual = _fit_background_residuals(z500, "geopotential_height_m")
        valid = residual.dropna().to_numpy(dtype=float)
        if valid.size:
            median = float(np.nanmedian(valid))
            mad = float(np.nanmedian(np.abs(valid - median)))
            threshold = max(float(config.z500_buddy_min_abs_m), float(config.z500_buddy_mad_factor) * 1.4826 * mad)
            outlier = residual.abs() > threshold
            mask = pd.Series(False, index=df.index)
            mask.loc[outlier.index] = outlier
            _flag(mask, "z500_buddy_outlier", flags)

    df = df.copy()
    df["qc_flags"] = [",".join(items) for items in flags]
    df["qc_status"] = np.where(df["qc_flags"].astype(bool), "reject", "pass")
    rejected = df["qc_status"].eq("reject")
    duplicate_mask = df.duplicated(subset=["station_id", "observation_time", "requested_level"], keep="last") & ~rejected
    _flag(duplicate_mask, "duplicate_station_level", flags)
    df["qc_flags"] = [",".join(items) for items in flags]
    df["qc_status"] = np.where(df["qc_flags"].astype(bool), "reject", "pass")

    counts: dict[str, int] = {}
    for items in flags:
        for item in items:
            counts[item] = counts.get(item, 0) + 1
    return df, counts


def _profile_summary(clean: pd.DataFrame, config: SoundingPreprocessConfig) -> dict[str, Any]:
    if clean.empty:
        return {"station_count": 0, "weak_profile_station_count": 0, "level_counts": {}, "standard_level_coverage": {}}
    level_counts = clean["requested_level"].value_counts().sort_index().to_dict()
    profile_levels = clean.groupby("station_id")["requested_level"].nunique()
    coverage = {}
    station_count = clean["station_id"].nunique()
    for level in STANDARD_LEVELS_HPA:
        key = f"{level}hPa"
        coverage[key] = round(float(level_counts.get(key, 0)) / max(float(station_count), 1.0), 3)
    return {
        "station_count": int(station_count),
        "weak_profile_station_count": int((profile_levels < int(config.min_profile_levels)).sum()),
        "profile_level_count_min": int(profile_levels.min()) if len(profile_levels) else 0,
        "profile_level_count_median": float(profile_levels.median()) if len(profile_levels) else 0.0,
        "profile_level_count_max": int(profile_levels.max()) if len(profile_levels) else 0,
        "level_counts": {str(key): int(value) for key, value in level_counts.items()},
        "standard_level_coverage": coverage,
    }


def _relative_display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def report_path_for(csv_path: str | Path) -> Path:
    path = _resolve_path(csv_path)
    return REPORT_DIR / f"{path.stem}.preprocess.json"


def cleaned_path_for(csv_path: str | Path) -> Path:
    path = _resolve_path(csv_path)
    return CLEANED_DIR / f"{path.stem}.clean.csv"


def load_preprocess_report(csv_path: str | Path) -> dict[str, Any]:
    path = report_path_for(csv_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return _read_json(path)


def preprocess_sounding_csv(
    csv_path: str | Path,
    *,
    config: SoundingPreprocessConfig | None = None,
    force: bool = False,
    write_outputs: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    cfg = config or SoundingPreprocessConfig()
    source = _resolve_path(csv_path)
    if not source.exists():
        raise FileNotFoundError(str(source))
    report_path = report_path_for(source)
    clean_path = cleaned_path_for(source)
    if report_path.exists() and clean_path.exists() and not force:
        return _read_json(report_path)

    raw = pd.read_csv(source)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in {_normalize_column_name(item) for item in raw.columns}]
    standardized = _standardize_dataframe(raw)
    qc, flag_counts = _add_qc_flags(standardized, cfg)
    clean = qc[qc["qc_status"].eq("pass")].copy()
    clean = clean.sort_values(["station_id", "observation_time", "pressure_hpa"], ascending=[True, True, False])
    profile = _profile_summary(clean, cfg)

    report = {
        "version": PREPROCESS_VERSION,
        "created_at": _now(),
        "source_path": _relative_display_path(source),
        "cleaned_csv_path": _relative_display_path(clean_path),
        "report_path": _relative_display_path(report_path),
        "missing_columns": missing_columns,
        "row_count": int(len(raw)),
        "accepted_row_count": int(len(clean)),
        "rejected_row_count": int(len(qc) - len(clean)),
        "reject_rate": round(float((len(qc) - len(clean)) / max(len(qc), 1)), 4),
        "flag_counts": {key: int(value) for key, value in sorted(flag_counts.items())},
        "profile": profile,
        "time_range": {
            "start": str(clean["observation_time"].min()) if not clean.empty else None,
            "end": str(clean["observation_time"].max()) if not clean.empty else None,
        },
        "domain": {
            "lat_min": float(clean["station_lat"].min()) if not clean.empty else None,
            "lat_max": float(clean["station_lat"].max()) if not clean.empty else None,
            "lon_min": float(clean["station_lon"].min()) if not clean.empty else None,
            "lon_max": float(clean["station_lon"].max()) if not clean.empty else None,
        },
        "quality_level": "high" if len(clean) and (len(qc) - len(clean)) / max(len(qc), 1) < 0.08 else "review",
    }

    if write_outputs:
        CLEANED_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        clean.to_csv(clean_path, index=False)
        _safe_write_json(report_path, report)
        _write_state()
    return report


def _reports() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in sorted(REPORT_DIR.glob("*.preprocess.json"), reverse=True):
        try:
            reports.append(_read_json(path))
        except Exception:
            pass
    return reports


def _write_state() -> None:
    PREPROCESS_DIR.mkdir(parents=True, exist_ok=True)
    reports = _reports()
    _safe_write_json(
        STATE_PATH,
        {
            "version": PREPROCESS_VERSION,
            "updated_at": _now(),
            "report_count": len(reports),
            "reports": reports[:20],
        },
    )


def _state_updated_at() -> str | None:
    if not STATE_PATH.exists():
        return None
    try:
        value = _read_json(STATE_PATH).get("updated_at")
        timestamp = _iso_datetime(value)
        if timestamp:
            return timestamp
    except Exception:
        pass
    return _iso_datetime(STATE_PATH.stat().st_mtime)


def preprocess_status(root: str | Path | None = None) -> dict[str, Any]:
    files = discover_sounding_csvs(root)
    reports = _reports()
    report_by_source = {item.get("source_path"): item for item in reports}
    return {
        "version": PREPROCESS_VERSION,
        "updated_at": _state_updated_at(),
        "available_file_count": len(files),
        "report_count": len(reports),
        "available_files": [
            {
                "path": _relative_display_path(path),
                "file_name": path.name,
                "has_report": _relative_display_path(path) in report_by_source,
                "report": report_by_source.get(_relative_display_path(path)),
            }
            for path in files
        ],
        "reports": reports[:20],
    }


def run_preprocess(
    *,
    csv_path: str | Path | None = None,
    root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    files = [_resolve_path(csv_path)] if csv_path else discover_sounding_csvs(root)
    results = []
    errors = []
    for path in files:
        try:
            results.append(preprocess_sounding_csv(path, force=force, write_outputs=True))
        except Exception as exc:
            errors.append({"path": _relative_display_path(path), "error": str(exc), "error_type": type(exc).__name__})
    _write_state()
    return {
        "version": PREPROCESS_VERSION,
        "processed_count": len(results),
        "failed_count": len(errors),
        "results": results,
        "errors": errors,
    }


def autostart_sounding_preprocess(root: str | Path | None = None) -> dict[str, Any] | None:
    if str(os.environ.get("WEATHER_DIAG_AUTO_SOUNDING_PREPROCESS", "1")).lower() in {"0", "false", "no", "off"}:
        return None

    files = discover_sounding_csvs(root)
    pending = [
        path for path in files
        if not report_path_for(path).exists() or not cleaned_path_for(path).exists()
    ]
    if not pending:
        if files:
            _write_state()
        return None

    global _AUTO_PREPROCESS_THREAD
    if _AUTO_PREPROCESS_THREAD and _AUTO_PREPROCESS_THREAD.is_alive():
        return {"status": "running", "pending_count": len(pending)}

    thread = threading.Thread(
        target=lambda: run_preprocess(root=root, force=False),
        name="sounding-preprocess-autostart",
        daemon=True,
    )
    _AUTO_PREPROCESS_THREAD = thread
    thread.start()
    return {"status": "queued", "pending_count": len(pending)}
