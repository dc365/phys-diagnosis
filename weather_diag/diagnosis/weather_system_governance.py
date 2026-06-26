from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather_diag.config import ADMIN_DIR, ensure_dirs


WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH = ADMIN_DIR / "weather_system_threshold_matrix.json"
WEATHER_SYSTEM_GOVERNANCE_VERSION = "weather-system-governance-v1"


class WeatherSystemGovernanceError(Exception):
    def __init__(self, msg: str, *, status_code: int = 400, data: dict | None = None):
        super().__init__(msg)
        self.msg = msg
        self.status_code = status_code
        self.data = data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parameter(
    entry_id: str,
    *,
    target: str,
    field: str,
    signal: str,
    statistic: str,
    operator: str,
    threshold: float,
    unit: str,
    source: str,
    section: str,
    key: str,
    value_type: str = "float",
    multiplier: float = 1.0,
    min_value: float | None = None,
    max_value: float | None = None,
) -> dict[str, Any]:
    return {
        "entry": {
            "entry_id": entry_id,
            "group": "天气系统",
            "target": target,
            "field": field,
            "signal": signal,
            "statistic": statistic,
            "operator": operator,
            "threshold": threshold,
            "scale": None,
            "weight": None,
            "unit": unit,
            "enabled": True,
            "source": source,
        },
        "config": {
            "section": section,
            "key": key,
            "value_type": value_type,
            "multiplier": multiplier,
            "min_value": min_value,
            "max_value": max_value,
        },
    }


WEATHER_SYSTEM_PARAMETER_SPECS = [
    # Wind shear lines and front-with-shear classification.
    _parameter(
        "system.shear_line.score_percentile",
        target="shear_line_850_700_500",
        field="shear_line_score",
        signal="切变线综合评分高值分位",
        statistic="percentile",
        operator=">=",
        threshold=84.0,
        unit="%",
        source="detect_shear_lines",
        section="shear_line",
        key="score_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.dynamic_percentile",
        target="shear_line_850_700_500",
        field="vorticity/convergence/deformation",
        signal="切变线动力支撑分位",
        statistic="percentile",
        operator=">=",
        threshold=75.0,
        unit="%",
        source="detect_shear_lines",
        section="shear_line",
        key="dynamic_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.vorticity_min_1e5",
        target="shear_line_850_700_500",
        field="relative_vorticity",
        signal="切变线最小正涡度",
        statistic="min",
        operator=">=",
        threshold=1.0,
        unit="10^-5/s",
        source="detect_shear_lines",
        section="shear_line",
        key="vorticity_min",
        multiplier=1.0e-5,
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.convergence_min_1e5",
        target="shear_line_850_700_500",
        field="convergence",
        signal="切变线最小辐合强度",
        statistic="min",
        operator=">=",
        threshold=0.4,
        unit="10^-5/s",
        source="detect_shear_lines",
        section="shear_line",
        key="convergence_min",
        multiplier=1.0e-5,
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.min_support_components",
        target="shear_line_850_700_500",
        field="dynamic_support",
        signal="切变线最少动力支撑项数",
        statistic="count",
        operator=">=",
        threshold=2.0,
        unit="component",
        source="detect_shear_lines",
        section="shear_line",
        key="min_support_components",
        value_type="int",
        min_value=1.0,
        max_value=3.0,
    ),
    _parameter(
        "system.shear_line.min_points",
        target="shear_line_850_700_500",
        field="shear_line_mask",
        signal="切变线候选连续区最小格点数",
        statistic="count",
        operator=">=",
        threshold=10.0,
        unit="grid",
        source="detect_shear_lines",
        section="shear_line",
        key="min_area_grid_points",
        value_type="int",
        min_value=1.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.shear_line.min_length_km",
        target="shear_line_850_700_500",
        field="shear_line_axis",
        signal="切变线轴最短长度",
        statistic="length",
        operator=">=",
        threshold=300.0,
        unit="km",
        source="detect_shear_lines",
        section="shear_line",
        key="min_length_km",
        min_value=0.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.shear_line.max_objects",
        target="shear_line_850_700_500",
        field="shear_line_score",
        signal="切变线最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=8.0,
        unit="object",
        source="detect_shear_lines",
        section="shear_line",
        key="max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.smoothing_sigma_grid",
        target="shear_line_850_700_500",
        field="uv850/uv700/uv500",
        signal="切变线风场平滑尺度",
        statistic="sigma",
        operator=">=",
        threshold=1.0,
        unit="grid",
        source="detect_shear_lines",
        section="shear_line",
        key="smoothing_sigma_grid",
        min_value=0.0,
        max_value=20.0,
    ),
    _parameter(
        "system.shear_line.front_gradient_percentile",
        target="shear_line_850_700_500",
        field="temperature_gradient",
        signal="锋区切变线温度梯度分位",
        statistic="percentile",
        operator=">=",
        threshold=85.0,
        unit="%",
        source="detect_shear_lines",
        section="shear_line",
        key="front_gradient_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.shear_line.front_with_shear_ratio_min",
        target="shear_line_850_700_500",
        field="front_like_ratio",
        signal="判为锋区切变线的最小锋区占比",
        statistic="ratio",
        operator=">=",
        threshold=0.45,
        unit="0-1",
        source="detect_shear_lines",
        section="shear_line",
        key="front_with_shear_ratio_min",
        min_value=0.0,
        max_value=1.0,
    ),
    _parameter(
        "system.shear_line.separate_front_with_shear",
        target="shear_line_850_700_500",
        field="front_like_mask",
        signal="是否细分锋区切变线（1开启/0关闭）",
        statistic="switch",
        operator=">=",
        threshold=1.0,
        unit="0/1",
        source="detect_shear_lines",
        section="shear_line",
        key="separate_front_with_shear",
        value_type="bool",
        min_value=0.0,
        max_value=1.0,
    ),
    # Mid-level vortex and cold-vortex candidates.
    _parameter(
        "system.vortex.smoothing_sigma_grid",
        target="vortex_500_700_850",
        field="gh500/gh700/gh850",
        signal="低涡高度场平滑尺度",
        statistic="sigma",
        operator=">=",
        threshold=1.2,
        unit="grid",
        source="detect_cold_vortex",
        section="vortex",
        key="smoothing_sigma_grid",
        min_value=0.0,
        max_value=20.0,
    ),
    _parameter(
        "system.vortex.min_distance_grid",
        target="vortex_500_700_850",
        field="geopotential_height",
        signal="低涡中心最小搜索半径",
        statistic="distance",
        operator=">=",
        threshold=8.0,
        unit="grid",
        source="detect_cold_vortex",
        section="vortex",
        key="min_distance_grid",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.vortex.max_objects",
        target="vortex_500_700_850",
        field="vortex_candidates",
        signal="低涡/冷涡最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=8.0,
        unit="object",
        source="detect_cold_vortex",
        section="vortex",
        key="max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.vortex.min_height_prominence",
        target="vortex_500_700_850",
        field="geopotential_height",
        signal="低涡中心最小高度显著度",
        statistic="prominence",
        operator=">=",
        threshold=20.0,
        unit="gpm",
        source="detect_cold_vortex",
        section="vortex",
        key="min_height_prominence",
        min_value=0.0,
        max_value=1000.0,
    ),
    _parameter(
        "system.vortex.closed_height_interval",
        target="vortex_500_700_850",
        field="geopotential_height",
        signal="闭合低值区高度间隔",
        statistic="interval",
        operator=">=",
        threshold=20.0,
        unit="gpm",
        source="detect_cold_vortex",
        section="vortex",
        key="closed_height_interval",
        min_value=0.1,
        max_value=1000.0,
    ),
    _parameter(
        "system.vortex.min_closed_area_km2",
        target="vortex_500_700_850",
        field="closed_vortex_area",
        signal="低涡闭合区最小面积",
        statistic="area",
        operator=">=",
        threshold=40000.0,
        unit="km2",
        source="detect_cold_vortex",
        section="vortex",
        key="min_closed_area_km2",
        min_value=0.0,
        max_value=10000000.0,
    ),
    _parameter(
        "system.vortex.vorticity_min_1e5",
        target="vortex_500_700_850",
        field="relative_vorticity",
        signal="低涡中心最小正涡度",
        statistic="min",
        operator=">=",
        threshold=1.0,
        unit="10^-5/s",
        source="detect_cold_vortex",
        section="vortex",
        key="vorticity_min",
        multiplier=1.0e-5,
        min_value=0.0,
        max_value=100.0,
    ),
    # Upper jet and jet-exit divergence regions.
    _parameter(
        "system.upper_jet.wind_speed_min",
        target="upper_jet_200_300",
        field="uv200/uv300",
        signal="高空急流风速下限",
        statistic="min",
        operator=">=",
        threshold=30.0,
        unit="m/s",
        source="detect_upper_jet",
        section="upper_jet",
        key="wind_speed_min_ms",
        min_value=0.0,
        max_value=200.0,
    ),
    _parameter(
        "system.upper_jet.wind_speed_percentile",
        target="upper_jet_200_300",
        field="upper_wind_speed",
        signal="高空急流风速高值分位",
        statistic="percentile",
        operator=">=",
        threshold=85.0,
        unit="%",
        source="detect_upper_jet",
        section="upper_jet",
        key="wind_speed_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.upper_jet.min_points",
        target="upper_jet_200_300",
        field="upper_jet_mask",
        signal="高空急流连续区最小格点数",
        statistic="count",
        operator=">=",
        threshold=10.0,
        unit="grid",
        source="detect_upper_jet",
        section="upper_jet",
        key="min_area_grid_points",
        value_type="int",
        min_value=1.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.upper_jet.min_direction_coherence",
        target="upper_jet_200_300",
        field="upper_wind_direction",
        signal="高空急流最小风向一致性",
        statistic="ratio",
        operator=">=",
        threshold=0.60,
        unit="0-1",
        source="detect_upper_jet",
        section="upper_jet",
        key="min_direction_coherence",
        min_value=0.0,
        max_value=1.0,
    ),
    _parameter(
        "system.upper_jet.rank_length_cap_km",
        target="upper_jet_200_300",
        field="upper_jet_axis",
        signal="高空急流排序长度封顶",
        statistic="length",
        operator="<=",
        threshold=2500.0,
        unit="km",
        source="detect_upper_jet",
        section="upper_jet",
        key="rank_length_cap_km",
        min_value=100.0,
        max_value=20000.0,
    ),
    _parameter(
        "system.upper_jet.max_objects",
        target="upper_jet_200_300",
        field="upper_jet_score",
        signal="高空急流最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=8.0,
        unit="object",
        source="detect_upper_jet",
        section="upper_jet",
        key="max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.upper_jet.smoothing_sigma_grid",
        target="upper_jet_200_300",
        field="uv200/uv300",
        signal="高空急流风场平滑尺度",
        statistic="sigma",
        operator=">=",
        threshold=1.0,
        unit="grid",
        source="detect_upper_jet",
        section="upper_jet",
        key="smoothing_sigma_grid",
        min_value=0.0,
        max_value=20.0,
    ),
    _parameter(
        "system.upper_jet.exit_divergence_min_1e5",
        target="upper_jet_exit_region",
        field="div200/div300",
        signal="急流出口区最小高空辐散",
        statistic="min",
        operator=">=",
        threshold=0.8,
        unit="10^-5/s",
        source="detect_jet_exit_regions",
        section="upper_jet",
        key="exit_divergence_min",
        multiplier=1.0e-5,
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.upper_jet.exit_divergence_percentile",
        target="upper_jet_exit_region",
        field="div200/div300",
        signal="急流出口区高空辐散分位",
        statistic="percentile",
        operator=">=",
        threshold=88.0,
        unit="%",
        source="detect_jet_exit_regions",
        section="upper_jet",
        key="exit_divergence_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.upper_jet.exit_min_points",
        target="upper_jet_exit_region",
        field="upper_jet_exit_mask",
        signal="急流出口区最小连续格点数",
        statistic="count",
        operator=">=",
        threshold=8.0,
        unit="grid",
        source="detect_jet_exit_regions",
        section="upper_jet",
        key="exit_min_area_grid_points",
        value_type="int",
        min_value=1.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.upper_jet.exit_max_objects",
        target="upper_jet_exit_region",
        field="upper_jet_exit_score",
        signal="急流出口区最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=6.0,
        unit="object",
        source="detect_jet_exit_regions",
        section="upper_jet",
        key="exit_max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    # Upper-level PV anomaly / dry intrusion.
    _parameter(
        "system.pv_anomaly.pv_percentile",
        target="pv_anomaly_300",
        field="pv300",
        signal="高空PV异常高值分位",
        statistic="percentile",
        operator=">=",
        threshold=90.0,
        unit="%",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="pv_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.pv_anomaly.pv_min",
        target="pv_anomaly_300",
        field="pv300",
        signal="高空PV异常绝对下限",
        statistic="min",
        operator=">=",
        threshold=1.5,
        unit="PVU",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="pv_min",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.pv_anomaly.min_points",
        target="pv_anomaly_300",
        field="pv_anomaly_mask",
        signal="PV异常区最小连续格点数",
        statistic="count",
        operator=">=",
        threshold=8.0,
        unit="grid",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="min_area_grid_points",
        value_type="int",
        min_value=1.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.pv_anomaly.max_objects",
        target="pv_anomaly_300",
        field="pv_anomaly_score",
        signal="PV异常区最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=8.0,
        unit="object",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.pv_anomaly.smoothing_sigma_grid",
        target="pv_anomaly_300",
        field="pv300",
        signal="PV场平滑尺度",
        statistic="sigma",
        operator=">=",
        threshold=1.0,
        unit="grid",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="smoothing_sigma_grid",
        min_value=0.0,
        max_value=20.0,
    ),
    _parameter(
        "system.pv_anomaly.require_positive_pv_advection",
        target="pv_anomaly_300",
        field="pvadv300",
        signal="是否要求正PV平流（1开启/0关闭）",
        statistic="switch",
        operator=">=",
        threshold=0.0,
        unit="0/1",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="require_positive_pv_advection",
        value_type="bool",
        min_value=0.0,
        max_value=1.0,
    ),
    _parameter(
        "system.pv_anomaly.mid_dry_rh_max",
        target="pv_anomaly_300",
        field="rh500",
        signal="干侵入中层相对湿度上限",
        statistic="max",
        operator="<=",
        threshold=65.0,
        unit="%",
        source="detect_pv_anomaly",
        section="pv_anomaly",
        key="mid_dry_rh_max",
        min_value=0.0,
        max_value=100.0,
    ),
    # Surface thermal and moisture boundaries.
    _parameter(
        "system.surface_boundary.score_percentile",
        target="surface_boundary",
        field="surface_boundary_score",
        signal="地面边界综合评分高值分位",
        statistic="percentile",
        operator=">=",
        threshold=86.0,
        unit="%",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="score_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.surface_boundary.temp_gradient_percentile",
        target="surface_boundary",
        field="t2m_gradient",
        signal="地面温度梯度高值分位",
        statistic="percentile",
        operator=">=",
        threshold=80.0,
        unit="%",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="temp_gradient_percentile",
        min_value=0.0,
        max_value=100.0,
    ),
    _parameter(
        "system.surface_boundary.min_points",
        target="surface_boundary",
        field="surface_boundary_mask",
        signal="地面边界连续区最小格点数",
        statistic="count",
        operator=">=",
        threshold=8.0,
        unit="grid",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="min_area_grid_points",
        value_type="int",
        min_value=1.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.surface_boundary.min_length_km",
        target="surface_boundary",
        field="surface_boundary_axis",
        signal="地面边界轴最短长度",
        statistic="length",
        operator=">=",
        threshold=120.0,
        unit="km",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="min_length_km",
        min_value=0.0,
        max_value=10000.0,
    ),
    _parameter(
        "system.surface_boundary.max_objects",
        target="surface_boundary",
        field="surface_boundary_score",
        signal="地面边界最大输出对象数",
        statistic="rank",
        operator="<=",
        threshold=8.0,
        unit="object",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="max_objects",
        value_type="int",
        min_value=1.0,
        max_value=100.0,
    ),
    _parameter(
        "system.surface_boundary.smoothing_sigma_grid",
        target="surface_boundary",
        field="t2m/td2m/uv10",
        signal="地面边界场平滑尺度",
        statistic="sigma",
        operator=">=",
        threshold=1.0,
        unit="grid",
        source="detect_surface_boundaries",
        section="surface_boundary",
        key="smoothing_sigma_grid",
        min_value=0.0,
        max_value=20.0,
    ),
]


PARAMETER_SPEC_BY_ID = {
    spec["entry"]["entry_id"]: spec
    for spec in WEATHER_SYSTEM_PARAMETER_SPECS
}
EXTRA_THRESHOLD_ENTRY_IDS = frozenset(PARAMETER_SPEC_BY_ID)


EXTRA_SYSTEM_CATALOG = [
    {
        "system_id": "shear_line_850_700_500",
        "name": "850/700/500hPa 切变线",
        "fields": ["uv850", "uv700", "uv500", "tt850/tt700/tt500", "q850/rh700/rh500"],
        "method": "正涡度、辐合和风场形变综合评分抽取切变轴；温度梯度强时细分为锋区切变线",
    },
    {
        "system_id": "vortex_500_700_850",
        "name": "500/700/850hPa 低涡与冷涡",
        "fields": ["gh500/gh700/gh850", "uv500/uv700/uv850", "tt500/tt700/tt850"],
        "method": "闭合高度低值中心、正涡度和可选冷心温度距平综合识别",
    },
    {
        "system_id": "upper_jet_200_300",
        "name": "200/300hPa 高空急流",
        "fields": ["uv200/uv300", "div200/div300"],
        "method": "高空风速高值带流线追踪急流轴，并以高空辐散提取急流出口区候选",
    },
    {
        "system_id": "pv_anomaly_300",
        "name": "300hPa PV异常与干侵入",
        "fields": ["pv300", "pvadv300", "rh500"],
        "method": "PV高值分位与绝对阈值联合识别，可选正PV平流和中层干空气约束",
    },
    {
        "system_id": "surface_boundary",
        "name": "地面锋区与干线候选",
        "fields": ["t2m", "td2m", "u10", "v10"],
        "method": "地面温度、露点梯度和10m风辐合综合评分抽取地面边界轴",
    },
    {
        "system_id": "convergence_divergence_axes",
        "name": "低层辐合轴与高空辐散轴",
        "fields": ["div850", "div200/div300", "uv850", "uv200/uv300"],
        "method": "从辐合/辐散连通区进一步抽取LineString主轴，业务图默认显示轴线",
    },
]


def _entry_ids_for_prefix(prefix: str) -> list[str]:
    return [entry_id for entry_id in EXTRA_THRESHOLD_ENTRY_IDS if entry_id.startswith(prefix)]


EXTRA_RULE_EXPLANATION_TEMPLATES = [
    {
        "rule_id": "shear_line_850_700_500",
        "title": "850/700/500hPa 切变线",
        "category": "天气系统",
        "purpose": "从低层和中层风场中识别气旋性风切变、辐合与形变共同支持的切变线轴。",
        "basis": [
            "切变线应同时具有正涡度、低层辐合或风场形变中的至少若干项支持。",
            "温度梯度较强且沿轴占比较高时输出 front_with_shear，否则输出 shear_line。",
            "候选区必须满足最小连通格点数和最短轴长，减少短小噪声线。",
        ],
        "inputs": [
            {"field": "uv850/uv700/uv500", "required": True, "role": "计算涡度、散度和形变"},
            {"field": "tt850/tt700/tt500", "required": False, "role": "区分普通切变线与锋区切变线"},
            {"field": "q850/rh700/rh500", "required": False, "role": "水汽或湿度弱支撑"},
        ],
        "method": [
            "score = positive_vorticity + convergence + deformation + wind_speed + optional_moisture",
            "mask = score高值分位 且 dynamic_support达到最少项数",
            "连通区抽取LineString轴线，按评分、强度和长度排序",
        ],
        "threshold_entries": sorted(_entry_ids_for_prefix("system.shear_line.")),
        "outputs": ["systems.type = shear_line / front_with_shear", "systems.geometry.type = line"],
        "evidence_contract": ["输出评分阈值、涡度阈值、辐合阈值、锋区占比和轴长"],
    },
    {
        "rule_id": "vortex_500_700_850",
        "title": "500/700/850hPa 低涡与冷涡",
        "category": "天气系统",
        "purpose": "识别天气尺度闭合高度低值中心，并结合正涡度与冷心结构区分低涡和冷涡候选。",
        "basis": [
            "位势高度场需存在局地低值和足够显著度。",
            "风场存在时要求中心附近正相对涡度达到阈值。",
            "温度负距平支持冷涡性质，缺少温度时只输出低涡候选。",
        ],
        "inputs": [
            {"field": "gh500/gh700/gh850", "required": True, "role": "闭合低值中心"},
            {"field": "uv500/uv700/uv850", "required": False, "role": "正涡度支撑"},
            {"field": "tt500/tt700/tt850", "required": False, "role": "冷心结构"},
        ],
        "method": [
            "天气尺度平滑后搜索局地高度极小值",
            "按高度显著度、闭合面积和正涡度过滤",
            "温度距平小于0时标记cold_vortex，否则标记mid_level_vortex",
        ],
        "threshold_entries": sorted(_entry_ids_for_prefix("system.vortex.")),
        "outputs": ["systems.type = cold_vortex / mid_level_vortex", "systems.geometry.type = point"],
        "evidence_contract": ["输出高度显著度、闭合面积、相对涡度和冷心距平"],
    },
    {
        "rule_id": "upper_jet_200_300",
        "title": "200/300hPa 高空急流与出口区",
        "category": "天气系统",
        "purpose": "识别高空急流轴，并结合高空辐散提取急流出口动力支撑区。",
        "basis": [
            "高空风速需同时满足绝对下限和区域高值分位。",
            "急流轴要求连续性和风向一致性，并对排序长度封顶，避免长而弱的轴优先。",
            "急流出口区由高空辐散绝对阈值和分位阈值共同约束。",
        ],
        "inputs": [
            {"field": "uv200/uv300", "required": True, "role": "高空急流风速和流向"},
            {"field": "div200/div300", "required": False, "role": "急流出口区辐散支撑"},
        ],
        "method": [
            "wind_threshold = max(absolute_min, wind_percentile)",
            "高值区沿风矢量追踪LineString急流轴",
            "高空散度高值连通区输出upper_jet_exit_region",
        ],
        "threshold_entries": sorted(_entry_ids_for_prefix("system.upper_jet.")),
        "outputs": ["systems.type = upper_jet / upper_jet_exit_region", "line + polygon geometry"],
        "evidence_contract": ["输出风速阈值、方向一致性、轴长、散度阈值和出口区面积"],
    },
    {
        "rule_id": "pv_anomaly_300",
        "title": "300hPa PV异常与干侵入",
        "category": "天气系统",
        "purpose": "识别高空PV异常区，作为槽前动力抬升、干侵入和强对流组织化的支撑诊断。",
        "basis": [
            "PV需同时达到绝对下限和区域高值分位。",
            "可选要求正PV平流，并可用中层相对湿度上限约束干侵入性质。",
            "PV异常默认作为支撑诊断层，不应替代槽线、冷涡和高空急流主体。",
        ],
        "inputs": [
            {"field": "pv300", "required": True, "role": "高空PV异常"},
            {"field": "pvadv300", "required": False, "role": "正PV平流"},
            {"field": "rh500", "required": False, "role": "中层干空气"},
        ],
        "method": [
            "pv_threshold = max(pv_min, pv_percentile)",
            "按可选正PV平流和中层干空气条件过滤",
            "连通区按最大和平均PV排序输出Polygon",
        ],
        "threshold_entries": sorted(_entry_ids_for_prefix("system.pv_anomaly.")),
        "outputs": ["systems.type = pv_anomaly", "systems.geometry.type = polygon"],
        "evidence_contract": ["输出PV阈值、最大/平均PV和中层干空气分数"],
    },
    {
        "rule_id": "surface_boundary",
        "title": "地面锋区与干线候选",
        "category": "天气系统",
        "purpose": "利用2m温度、露点和10m风识别地面热力边界、露点锋和干线候选。",
        "basis": [
            "地面温度梯度是基础判据，露点梯度和10m风辐合提供增强证据。",
            "露点梯度相对占优时标记dryline_candidate，否则标记surface_front_candidate。",
            "该算法对地形和下垫面敏感，需结合实况订正。",
        ],
        "inputs": [
            {"field": "t2m", "required": True, "role": "地面温度梯度"},
            {"field": "td2m", "required": False, "role": "露点梯度与干线"},
            {"field": "u10/v10", "required": False, "role": "地面风辐合"},
        ],
        "method": [
            "score = temperature_gradient + dewpoint_gradient + optional_convergence",
            "候选区同时满足综合评分和温度梯度分位",
            "连通区抽取LineString轴线，并按评分与长度排序",
        ],
        "threshold_entries": sorted(_entry_ids_for_prefix("system.surface_boundary.")),
        "outputs": ["systems.type = surface_front_candidate / dryline_candidate", "systems.geometry.type = line"],
        "evidence_contract": ["输出温度梯度、露点梯度、地面辐合、轴长和评分"],
    },
]


def default_extra_threshold_entries() -> list[dict[str, Any]]:
    return [deepcopy(spec["entry"]) for spec in WEATHER_SYSTEM_PARAMETER_SPECS]


def _normalize_threshold(spec: dict[str, Any], value: Any) -> float:
    entry_id = spec["entry"]["entry_id"]
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherSystemGovernanceError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": "threshold", "entry_id": entry_id},
        ) from exc
    config = spec["config"]
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    if min_value is not None and number < float(min_value):
        raise WeatherSystemGovernanceError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": "threshold", "entry_id": entry_id, "min": min_value},
        )
    if max_value is not None and number > float(max_value):
        raise WeatherSystemGovernanceError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": "threshold", "entry_id": entry_id, "max": max_value},
        )
    value_type = config.get("value_type")
    if value_type == "int" and abs(number - round(number)) > 1.0e-9:
        raise WeatherSystemGovernanceError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": "threshold", "entry_id": entry_id, "expected": "integer"},
        )
    if value_type == "bool" and number not in {0.0, 1.0}:
        raise WeatherSystemGovernanceError(
            "invalid threshold matrix",
            status_code=400,
            data={"field": "threshold", "entry_id": entry_id, "expected": "0 or 1"},
        )
    return number


def _merge_extra_entries(saved_entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    submitted = {str(item.get("entry_id") or ""): dict(item) for item in saved_entries or []}
    merged = []
    for spec in WEATHER_SYSTEM_PARAMETER_SPECS:
        default = deepcopy(spec["entry"])
        raw = submitted.get(default["entry_id"])
        if raw:
            default["threshold"] = _normalize_threshold(spec, raw.get("threshold", default["threshold"]))
            default["enabled"] = bool(raw.get("enabled", default["enabled"]))
        merged.append(default)
    return merged


def load_extra_threshold_state() -> dict[str, Any]:
    ensure_dirs()
    if not WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.exists():
        return {
            "version": WEATHER_SYSTEM_GOVERNANCE_VERSION,
            "updated_at": None,
            "updated_by": None,
            "remark": "",
            "entries": default_extra_threshold_entries(),
        }
    try:
        data = json.loads(WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WeatherSystemGovernanceError(
            "weather system threshold matrix unreadable",
            status_code=500,
        ) from exc
    data = dict(data)
    return {
        "version": WEATHER_SYSTEM_GOVERNANCE_VERSION,
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "remark": str(data.get("remark") or ""),
        "entries": _merge_extra_entries(list(data.get("entries") or [])),
    }


def _entry_settings(entries: list[dict[str, Any]]) -> list[tuple[str, float, bool]]:
    return [
        (str(entry["entry_id"]), float(entry["threshold"]), bool(entry.get("enabled", True)))
        for entry in entries
    ]


def save_extra_threshold_entries(
    entries: list[dict[str, Any]],
    *,
    updated_by: str | None = None,
    remark: str | None = None,
) -> dict[str, Any]:
    ensure_dirs()
    normalized = _merge_extra_entries(entries)
    defaults = default_extra_threshold_entries()
    if _entry_settings(normalized) == _entry_settings(defaults):
        WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.unlink(missing_ok=True)
        return load_extra_threshold_state()
    state = {
        "version": WEATHER_SYSTEM_GOVERNANCE_VERSION,
        "updated_at": _utc_now(),
        "updated_by": str(updated_by or "admin"),
        "remark": str(remark or ""),
        "entries": normalized,
    }
    WEATHER_SYSTEM_THRESHOLD_MATRIX_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return state


def merge_threshold_matrix(base_matrix: dict[str, Any]) -> dict[str, Any]:
    matrix = deepcopy(base_matrix)
    state = load_extra_threshold_state()
    base_entries = list(matrix.get("entries") or [])
    base_ids = {str(entry.get("entry_id") or "") for entry in base_entries}
    matrix["entries"] = base_entries + [
        entry for entry in state["entries"]
        if entry["entry_id"] not in base_ids
    ]
    matrix["weather_system_governance"] = {
        "version": state["version"],
        "updated_at": state.get("updated_at"),
        "updated_by": state.get("updated_by"),
        "entry_count": len(state["entries"]),
    }
    return matrix


def augment_catalog_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    algorithms = result.get("algorithms") or []
    if algorithms:
        systems = algorithms[0].setdefault("systems", [])
        existing = {str(item.get("system_id") or "") for item in systems}
        for item in EXTRA_SYSTEM_CATALOG:
            if item["system_id"] in existing:
                continue
            system = deepcopy(item)
            system["governance_domain"] = "weather-systems"
            systems.append(system)
    result["threshold_matrix"] = merge_threshold_matrix(result.get("threshold_matrix") or {})
    return result


def augment_rule_explanations_payload(
    payload: dict[str, Any],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(payload)
    by_id = {str(entry.get("entry_id") or ""): entry for entry in matrix.get("entries") or []}
    sections = result.setdefault("sections", [])
    existing = {str(section.get("rule_id") or "") for section in sections}
    for template in EXTRA_RULE_EXPLANATION_TEMPLATES:
        if template["rule_id"] in existing:
            continue
        section = deepcopy(template)
        section["governance_domain"] = "weather-systems"
        threshold_ids = list(section.get("threshold_entries") or [])
        section["threshold_details"] = [deepcopy(by_id[entry_id]) for entry_id in threshold_ids if entry_id in by_id]
        section["missing_threshold_entries"] = [entry_id for entry_id in threshold_ids if entry_id not in by_id]
        section["enabled_threshold_count"] = sum(
            1 for entry in section["threshold_details"] if bool(entry.get("enabled", True))
        )
        sections.append(section)
    result["matrix_updated_at"] = matrix.get("updated_at")
    return result


def _convert_config_value(spec: dict[str, Any], threshold: float) -> Any:
    config = spec["config"]
    value = float(threshold) * float(config.get("multiplier", 1.0))
    value_type = config.get("value_type")
    if value_type == "int":
        return int(round(value))
    if value_type == "bool":
        return bool(round(value))
    return value


def apply_governance_thresholds(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    state = load_extra_threshold_state()
    for entry in state["entries"]:
        if not bool(entry.get("enabled", True)):
            continue
        spec = PARAMETER_SPEC_BY_ID[entry["entry_id"]]
        section = spec["config"]["section"]
        key = spec["config"]["key"]
        result.setdefault(section, {})[key] = _convert_config_value(spec, float(entry["threshold"]))
    return result
