from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from weather_diag.config import CONFIG_DIR


@dataclass(frozen=True)
class AreaStation:
    station_id: str
    station_code: str
    station_name: str
    lon: float
    lat: float
    city_code: str
    city_name: str
    county_code: str
    county_name: str
    town_code: str
    town_name: str
    display_name: str
    s5_code: str = ""
    s8_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "station_code": self.station_code,
            "station_name": self.station_name,
            "lon": self.lon,
            "lat": self.lat,
            "city_code": self.city_code,
            "city_name": self.city_name,
            "county_code": self.county_code,
            "county_name": self.county_name,
            "town_code": self.town_code,
            "town_name": self.town_name,
            "display_name": self.display_name,
            "s5": self.s5_code,
            "s8": self.s8_code,
        }


@dataclass(frozen=True)
class TownArea:
    code: str
    name: str
    city_code: str
    city_name: str
    county_code: str
    county_name: str
    points: tuple[AreaStation, ...]

    @property
    def station_count(self) -> int:
        return len(self.points)

    @property
    def bbox(self) -> list[float]:
        if not self.points:
            return []
        lons = [point.lon for point in self.points]
        lats = [point.lat for point in self.points]
        return [min(lons), min(lats), max(lons), max(lats)]

    def to_dict(self, *, include_points: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "town_code": self.code,
            "town_name": self.name,
            "s5": self.points[0].s5_code if self.points else "",
            "city_code": self.city_code,
            "city_name": self.city_name,
            "county_code": self.county_code,
            "county_name": self.county_name,
            "station_count": self.station_count,
            "bbox": self.bbox,
        }
        if include_points:
            data["points"] = [point.to_dict() for point in self.points]
        return data


class AreaRegistry:
    def __init__(self, towns: Iterable[TownArea]):
        ordered = sorted(
            towns,
            key=lambda item: (item.city_code, item.county_code, item.code),
        )
        self._towns = {town.code: town for town in ordered}
        self._city_index = _index_towns(ordered, "city_code")
        self._county_index = _index_towns(ordered, "county_code")

    def get_town(self, town_code: str) -> TownArea:
        return self._towns[str(town_code)]

    def towns_for_region(self, region_code: str, *, region_level: str | None = None) -> list[TownArea]:
        code = str(region_code)
        level = _normalize_region_level(region_level)
        if level == "town":
            return [self.get_town(code)] if code in self._towns else []
        if level == "county":
            return list(self._county_index.get(code, []))
        if level == "city":
            return list(self._city_index.get(code, []))
        if code in self._towns:
            return [self._towns[code]]
        if code in self._county_index:
            return list(self._county_index[code])
        if code in self._city_index:
            return list(self._city_index[code])
        return []

    def all_towns(self) -> list[TownArea]:
        return list(self._towns.values())


def _index_towns(towns: Iterable[TownArea], attr: str) -> dict[str, list[TownArea]]:
    out: dict[str, list[TownArea]] = {}
    for town in towns:
        out.setdefault(str(getattr(town, attr)), []).append(town)
    return out


def _normalize_region_level(value: str | None) -> str | None:
    if not value:
        return None
    aliases = {
        "cityCode": "city",
        "city_code": "city",
        "area": "city",
        "areaCode": "city",
        "area_code": "city",
        "countyCode": "county",
        "county_code": "county",
        "district": "county",
        "townCode": "town",
        "town_code": "town",
    }
    raw = str(value).strip()
    return aliases.get(raw, raw)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_station(record: dict[str, Any], *, default_city_code: str = "") -> AreaStation | None:
    lon = _as_float(record.get("longitude"))
    lat = _as_float(record.get("latitude"))
    town_code = str(record.get("townCode") or "").strip()
    town_name = str(record.get("town") or "").strip()
    if lon is None or lat is None or not town_code or not town_name:
        return None
    return AreaStation(
        station_id=str(record.get("stationId") or ""),
        station_code=str(record.get("stationCode") or ""),
        station_name=str(record.get("stationName") or ""),
        lon=lon,
        lat=lat,
        city_code=str(record.get("cityCode") or default_city_code),
        city_name=str(record.get("city") or ""),
        county_code=str(record.get("countyCode") or ""),
        county_name=str(record.get("county") or ""),
        town_code=town_code,
        town_name=town_name,
        display_name=str(record.get("displayName") or ""),
        s5_code=str(record.get("s5") or ""),
        s8_code=str(record.get("s8") or ""),
    )


def _towns_from_files(config_dir: Path) -> list[TownArea]:
    grouped: dict[str, list[AreaStation]] = {}
    for path in sorted(config_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("data") or {}
        default_city_code = str(data.get("areaCode") or "")
        for raw in data.get("records") or []:
            if not isinstance(raw, dict):
                continue
            station = _record_station(raw, default_city_code=default_city_code)
            if station is None:
                continue
            grouped.setdefault(station.town_code, []).append(station)

    towns: list[TownArea] = []
    for town_code, points in grouped.items():
        first = points[0]
        towns.append(
            TownArea(
                code=town_code,
                name=first.town_name,
                city_code=first.city_code,
                city_name=first.city_name,
                county_code=first.county_code,
                county_name=first.county_name,
                points=tuple(points),
            )
        )
    return towns


@lru_cache(maxsize=8)
def _load_area_registry_cached(config_dir: str) -> AreaRegistry:
    return AreaRegistry(_towns_from_files(Path(config_dir)))


def load_area_registry(config_dir: str | Path | None = None) -> AreaRegistry:
    area_dir = Path(config_dir) if config_dir is not None else CONFIG_DIR / "areas"
    return _load_area_registry_cached(str(area_dir.resolve()))
