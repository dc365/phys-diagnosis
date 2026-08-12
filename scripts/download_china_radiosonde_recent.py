from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JSON_BASE = "https://weather.uwyo.edu/wsgi/sounding_json"
SOUNDING_BASE = "https://weather.uwyo.edu/wsgi/sounding"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "test_datas"
BJT = timezone(timedelta(hours=8))
SCOPE_CONFIGS = {
    "china": {
        "scope_name": "china",
        "scope_label": "中国探空站",
        "dir_prefix": "china_radiosonde",
        "file_prefix": "china_radiosonde",
        "station_filter": "china",
        "selection_rule": "数据抓取使用最近两个完整 UTC 日的标准探空时次 00Z/12Z，输出时间统一转换为北京时间",
    },
    "regional_5n55n_50e160e": {
        "scope_name": "regional_5n55n_50e160e",
        "scope_label": "5N-55N, 50E-160E 区域探空站",
        "dir_prefix": "regional_radiosonde_5N55N_50E160E",
        "file_prefix": "regional_radiosonde_5N55N_50E160E",
        "station_filter": "bbox",
        "bbox": {"min_lat": 5.0, "max_lat": 55.0, "min_lon": 50.0, "max_lon": 160.0},
        "selection_rule": "数据抓取使用最近两个完整 UTC 日的标准探空时次 00Z/12Z，站点范围为 5N-55N、50E-160E，输出时间统一转换为北京时间",
    },
}
TARGET_LEVELS: list[tuple[str, float | None]] = [
    ("surface", None),
    ("1000hPa", 1000.0),
    ("950hPa", 950.0),
    ("925hPa", 925.0),
    ("850hPa", 850.0),
    ("800hPa", 800.0),
    ("750hPa", 750.0),
    ("700hPa", 700.0),
    ("600hPa", 600.0),
    ("500hPa", 500.0),
    ("400hPa", 400.0),
    ("300hPa", 300.0),
    ("250hPa", 250.0),
    ("200hPa", 200.0),
    ("150hPa", 150.0),
    ("100hPa", 100.0),
]
TARGET_LEVEL_INDEX = {level_name: index for index, (level_name, _) in enumerate(TARGET_LEVELS)}
CHINESE_STATION_NAMES = {
    "45004": "香港京士柏",
    "50527": "海拉尔",
    "50557": "嫩江",
    "50774": "伊春",
    "50953": "哈尔滨",
    "51076": "阿勒泰",
    "51431": "伊宁",
    "51463": "乌鲁木齐",
    "51644": "库车",
    "51709": "喀什",
    "51777": "若羌",
    "51828": "和田",
    "51839": "民丰",
    "52203": "哈密",
    "52267": "额济纳旗",
    "52323": "马鬃山",
    "52418": "敦煌",
    "52533": "酒泉",
    "52681": "民勤",
    "52818": "格尔木",
    "52836": "都兰",
    "52866": "西宁",
    "52983": "榆中",
    "53068": "二连浩特",
    "53463": "呼和浩特",
    "53513": "临河",
    "53614": "银川",
    "53772": "太原",
    "53845": "延安",
    "53915": "平凉",
    "54102": "锡林浩特",
    "54135": "通辽",
    "54161": "长春",
    "54218": "赤峰",
    "54292": "延吉",
    "54340": "沈阳",
    "54374": "临江",
    "54511": "北京",
    "54662": "大连",
    "54727": "章丘",
    "54857": "青岛",
    "55299": "那曲",
    "55591": "拉萨",
    "56029": "玉树",
    "56080": "合作",
    "56137": "昌都",
    "56146": "甘孜",
    "56187": "温江",
    "56571": "西昌",
    "56691": "威宁",
    "56739": "腾冲",
    "56778": "昆明",
    "56964": "思茅",
    "56985": "蒙自",
    "57083": "郑州",
    "57127": "汉中",
    "57131": "泾河",
    "57178": "南阳",
    "57461": "宜昌",
    "57494": "武汉",
    "57516": "重庆",
    "57541": "竹山",
    "57687": "长沙",
    "57749": "怀化",
    "57816": "贵阳",
    "57957": "桂林",
    "57972": "郴州",
    "57993": "赣州",
    "58027": "徐州",
    "58150": "射阳",
    "58203": "阜阳",
    "58238": "南京",
    "58362": "上海",
    "58424": "安庆",
    "58457": "杭州",
    "58606": "南昌",
    "58633": "衢州",
    "58665": "洪家",
    "58725": "邵武",
    "58847": "福州",
    "59134": "厦门",
    "59211": "百色",
    "59265": "梧州",
    "59280": "清远",
    "59316": "汕头",
    "59431": "南宁",
    "59758": "海口",
    "59981": "西沙",
}
FIELDNAMES = [
    "request_datetime_bjt",
    "requested_level",
    "station_id",
    "station_name",
    "station_lat",
    "station_lon",
    "station_src",
    "observation_time_bjt",
    "obs_longitude",
    "obs_latitude",
    "pressure_hpa",
    "geopotential_height_m",
    "temperature_c",
    "dew_point_temperature_c",
    "ice_point_temperature_c",
    "relative_humidity_pct",
    "humidity_wrt_ice_pct",
    "mixing_ratio_g_per_kg",
    "wind_direction_degree",
    "wind_speed_m_s",
]


def fetch_text(url: str) -> str:
    last_error = None
    for attempt in range(4):
        request = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == 3:
                break
            time.sleep(2 * (attempt + 1))
    raise last_error


def fetch_json(url: str) -> dict:
    return json.loads(fetch_text(url))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_float(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_utc_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def utc_to_bjt_str(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    return parse_utc_datetime(value).astimezone(BJT).strftime("%Y-%m-%d %H:%M:%S")


def utc_to_bjt_file_tag(value: str) -> str:
    bjt_value = parse_utc_datetime(value).astimezone(BJT)
    return bjt_value.strftime("%Y%m%d_%H") + "BJT"


def target_datetimes() -> list[str]:
    today_utc = datetime.now(timezone.utc).date()
    latest_complete_day = today_utc - timedelta(days=1)
    previous_complete_day = today_utc - timedelta(days=2)
    dates = [previous_complete_day, latest_complete_day]
    datetimes = []
    for date_value in dates:
        datetimes.append(f"{date_value.isoformat()} 00:00:00")
        datetimes.append(f"{date_value.isoformat()} 12:00:00")
    return datetimes


def resolve_scope(scope_name: str) -> dict[str, Any]:
    scope = SCOPE_CONFIGS.get(scope_name)
    if scope is None:
        supported = ", ".join(sorted(SCOPE_CONFIGS))
        raise SystemExit(f"Unsupported scope: {scope_name}. Supported scopes: {supported}")
    return scope


def is_china_station(station: dict) -> bool:
    stationid = station.get("stationid", "")
    name = station.get("name", "")
    return ("China" in name and stationid.startswith("5")) or stationid == "45004"


def station_in_bbox(station: dict, bbox: dict[str, float]) -> bool:
    lat = station.get("lat")
    lon = station.get("lon")
    if lat is None or lon is None:
        return False
    return bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lon <= bbox["max_lon"]


def station_in_scope(station: dict, scope: dict[str, Any]) -> bool:
    if scope["station_filter"] == "china":
        return is_china_station(station)
    if scope["station_filter"] == "bbox":
        return station_in_bbox(station, scope["bbox"])
    return False


def station_name_zh(stationid: str, fallback_name: str) -> str:
    return CHINESE_STATION_NAMES.get(stationid, fallback_name)


def select_profile_levels(profile_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows_with_pressure = [row for row in profile_rows if parse_float(row["pressure_hpa"]) is not None]
    if not rows_with_pressure:
        return []

    surface_row = max(rows_with_pressure, key=lambda row: parse_float(row["pressure_hpa"]) or float("-inf"))
    selected_rows = []
    for level_name, target_pressure in TARGET_LEVELS:
        if target_pressure is None:
            matched_row = surface_row
        else:
            matched_row = min(
                rows_with_pressure,
                key=lambda row: (
                    abs((parse_float(row["pressure_hpa"]) or target_pressure) - target_pressure),
                    -1 * (parse_float(row["pressure_hpa"]) or 0.0),
                ),
            )
        selected_rows.append({"requested_level": level_name, **matched_row})
    return selected_rows


def fetch_station_csv(request_datetime: str, station: dict) -> dict:
    url = SOUNDING_BASE + "?" + urllib.parse.urlencode(
        {
            "datetime": request_datetime,
            "id": station["stationid"],
            "src": station["src"],
            "type": "TEXT:CSV",
        }
    )
    text = fetch_text(url)
    if text.lstrip().startswith("<!DOCTYPE html>") or "Can't get" in text:
        return {
            "stationid": station["stationid"],
            "name": station_name_zh(station["stationid"], station.get("name", "")),
            "status": "missing",
            "url": url,
            "rows": [],
        }

    reader = csv.DictReader(io.StringIO(text))
    station_name = station_name_zh(station["stationid"], station.get("name", ""))
    request_datetime_bjt = utc_to_bjt_str(request_datetime)
    profile_rows = []
    for row in reader:
        profile_rows.append(
            {
                "request_datetime_bjt": request_datetime_bjt,
                "station_id": station["stationid"],
                "station_name": station_name,
                "station_lat": station.get("lat"),
                "station_lon": station.get("lon"),
                "station_src": station.get("src", ""),
                "observation_time_bjt": utc_to_bjt_str(clean_text(row.get("time", ""))),
                "obs_longitude": clean_text(row.get("longitude", "")),
                "obs_latitude": clean_text(row.get("latitude", "")),
                "pressure_hpa": clean_text(row.get("pressure_hPa", "")),
                "geopotential_height_m": clean_text(row.get("geopotential height_m", "")),
                "temperature_c": clean_text(row.get("temperature_C", "")),
                "dew_point_temperature_c": clean_text(row.get("dew point temperature_C", "")),
                "ice_point_temperature_c": clean_text(row.get("ice point temperature_C", "")),
                "relative_humidity_pct": clean_text(row.get("relative humidity_%", "")),
                "humidity_wrt_ice_pct": clean_text(row.get("humidity wrt ice_%", "")),
                "mixing_ratio_g_per_kg": clean_text(row.get("mixing ratio_g/kg", "")),
                "wind_direction_degree": clean_text(row.get("wind direction_degree", "")),
                "wind_speed_m_s": clean_text(row.get("wind speed_m/s", "")),
            }
        )
    rows = select_profile_levels(profile_rows)
    return {
        "stationid": station["stationid"],
        "name": station_name,
        "status": "ok",
        "url": url,
        "rows": rows,
    }


def write_station_manifest(path: Path, stations: dict) -> None:
    rows = []
    for stationid in sorted(stations):
        station = stations[stationid]
        rows.append(
            {
                "station_id": station["stationid"],
                "station_name": station["name_zh"],
                "station_name_en": station["name_en"],
                "lat": station["lat"],
                "lon": station["lon"],
                "sources": "|".join(sorted(station["sources"])),
                "available_datetimes_bjt": "|".join(station["available_datetimes"]),
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "station_id",
                "station_name",
                "station_name_en",
                "lat",
                "lon",
                "sources",
                "available_datetimes_bjt",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    scope_name = sys.argv[1] if len(sys.argv) > 1 else "china"
    scope = resolve_scope(scope_name)
    requested_cycles = target_datetimes()
    first_day = requested_cycles[0][:10].replace("-", "")
    last_day = requested_cycles[-1][:10].replace("-", "")
    out_dir = OUTPUT_ROOT / f"{scope['dir_prefix']}_{first_day}_{last_day}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cycle_stations: dict[str, list[dict]] = {}
    union_stations: dict[str, dict] = {}
    for request_datetime in requested_cycles:
        stations_url = JSON_BASE + "?" + urllib.parse.urlencode({"datetime": request_datetime})
        payload = fetch_json(stations_url)
        scoped_stations = [station for station in payload["stations"] if station_in_scope(station, scope)]
        scoped_stations.sort(key=lambda item: item["stationid"])
        cycle_stations[request_datetime] = scoped_stations
        for station in scoped_stations:
            record = union_stations.setdefault(
                station["stationid"],
                {
                    "stationid": station["stationid"],
                    "name_zh": station_name_zh(station["stationid"], station.get("name", "")),
                    "name_en": station.get("name", ""),
                    "lat": station.get("lat"),
                    "lon": station.get("lon"),
                    "sources": set(),
                    "available_datetimes": [],
                },
            )
            record["sources"].add(station.get("src", "UNKNOWN"))
            record["available_datetimes"].append(utc_to_bjt_str(request_datetime))

    write_station_manifest(out_dir / "stations_manifest.csv", union_stations)

    report = {
        "source": "University of Wyoming Atmospheric Science Radiosonde Archive",
        "scope_name": scope["scope_name"],
        "scope_label": scope["scope_label"],
        "source_station_api": JSON_BASE,
        "source_sounding_api": SOUNDING_BASE,
        "selection_rule": scope["selection_rule"],
        "target_datetimes_bjt": [utc_to_bjt_str(value) for value in requested_cycles],
        "requested_levels": [level_name for level_name, _ in TARGET_LEVELS],
        "station_count_union": len(union_stations),
        "cycles": {},
    }
    if "bbox" in scope:
        report["bbox"] = scope["bbox"]

    for request_datetime in requested_cycles:
        request_datetime_bjt = utc_to_bjt_str(request_datetime)
        cycle_rows = []
        missing_stations = []
        stations = cycle_stations[request_datetime]
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(fetch_station_csv, request_datetime, station) for station in stations]
            for future in as_completed(futures):
                result = future.result()
                if result["status"] == "ok":
                    cycle_rows.extend(result["rows"])
                else:
                    missing_stations.append(
                        {
                            "stationid": result["stationid"],
                            "name": result["name"],
                            "url": result["url"],
                        }
                    )

        cycle_rows.sort(
            key=lambda row: (
                row["station_id"],
                TARGET_LEVEL_INDEX[row["requested_level"]],
            )
        )
        file_name = f"{scope['file_prefix']}_{utc_to_bjt_file_tag(request_datetime)}.csv"
        with (out_dir / file_name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(cycle_rows)

        report["cycles"][request_datetime_bjt] = {
            "stations_in_cycle": len(stations),
            "rows_written": len(cycle_rows),
            "missing_station_count": len(missing_stations),
            "missing_stations": sorted(missing_stations, key=lambda item: item["stationid"]),
            "output_file": file_name,
        }

    with (out_dir / "download_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    readme = "\n".join(
        [
            "中国气象探空基础要素下载说明",
            "",
            "数据源: University of Wyoming Atmospheric Science Radiosonde Archive",
            f"范围: {scope['scope_label']}",
            f"下载目录: {out_dir.name}",
            f"时间选择: {scope['selection_rule']}",
            f"时次: {', '.join(utc_to_bjt_str(value) for value in requested_cycles)}",
            f"站点并集数量: {len(union_stations)}",
            "层次选择: 地面层 + 1000/950/925/850/800/750/700/600/500/400/300/250/200/150/100hPa",
            "选层方法: 对每个目标气压层，从原始探空剖面中选取 pressure_hpa 最接近的一条记录。",
            "站名说明: 中国站优先使用中文名，非中国站保留资料源原始站名。",
            "文件说明:",
            "- stations_manifest.csv: 站点清单，主站名为中文，附英文原名供核对，时次字段为北京时间",
            f"- {scope['file_prefix']}_YYYYMMDD_HHBJT.csv: 单个时次下全部区域站的指定层次基础要素合并表，文件名时间为北京时间",
            "- download_report.json: 每个时次的站点数、行数、缺测站列表",
            "字段说明:",
            "- request_datetime_bjt, requested_level, station_id, station_name, station_lat, station_lon, station_src",
            "- observation_time_bjt, obs_longitude, obs_latitude, pressure_hpa, geopotential_height_m",
            "- temperature_c, dew_point_temperature_c, ice_point_temperature_c",
            "- relative_humidity_pct, humidity_wrt_ice_pct, mixing_ratio_g_per_kg, wind_direction_degree, wind_speed_m_s",
        ]
    )
    (out_dir / "README.txt").write_text(readme, encoding="utf-8")

    print(f"输出目录: {out_dir}")
    print(f"范围: {scope['scope_label']}")
    print(f"站点并集数量: {len(union_stations)}")
    for request_datetime in requested_cycles:
        cycle = report["cycles"][utc_to_bjt_str(request_datetime)]
        print(
            f"{utc_to_bjt_str(request_datetime)} stations={cycle['stations_in_cycle']} rows={cycle['rows_written']} missing={cycle['missing_station_count']}"
        )
