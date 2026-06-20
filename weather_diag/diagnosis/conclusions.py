from __future__ import annotations

from typing import Any

from weather_diag.diagnosis.system_links import TYPE_LABELS


TARGET_LABELS = {
    "heavy_rain_potential": "强降水潜势",
    "convection_potential": "强对流潜势",
    "dynamic_lift_potential": "动力抬升潜势",
    "precipitation_phase": "雨雪相态",
    "heavy_rain_risk": "强降水风险区",
    "convection_risk": "强对流风险区",
}


LEVEL_LABELS = {
    "high": "高",
    "moderate": "中等",
    "low": "偏低",
    "core": "核心区",
    "outer": "外围区",
}


SIGNAL_LABELS = {
    "low-level moisture": "低层水汽",
    "column water vapor": "整层可降水量",
    "moisture transport": "低层水汽输送",
    "low-level convergence": "低层辐合",
    "700hPa upward motion": "700hPa 上升运动",
    "convective instability": "对流不稳定",
    "CAPE support": "CAPE 支持",
    "model 6h precipitation": "模式 6 小时降水",
    "instability energy": "不稳定能量",
    "inhibition is not excessive": "对流抑制不强",
    "thermodynamic instability": "热力不稳定",
    "deep-layer shear": "深层垂直风切变",
    "low-level trigger": "低层触发",
    "upper-level divergence": "高空辐散",
    "upper-level PV support": "高空 PV 支持",
    "PV advection support": "PV 平流支持",
}


def _level_label(level: str | None) -> str:
    return LEVEL_LABELS.get(str(level or ""), str(level or "未知"))


def _target_label(target_type: str) -> str:
    return TARGET_LABELS.get(target_type, target_type)


def _signal_label(signal: str) -> str:
    return SIGNAL_LABELS.get(signal, signal)


def _format_score(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _dominant_text(items: list[dict[str, Any]], *, limit: int = 3) -> str:
    parts = []
    for item in items[:limit]:
        label = item.get("label") or _signal_label(str(item.get("signal") or item.get("entry_id") or "证据"))
        value = item.get("value")
        contribution = item.get("contribution") or item.get("mean_contribution")
        if contribution is not None:
            parts.append(f"{label}贡献{float(contribution):.2f}")
        elif value:
            parts.append(f"{label}{value}")
        else:
            parts.append(str(label))
    return "、".join(parts)


def _systems_text(items: list[dict[str, Any]], *, limit: int = 4) -> str:
    labels = []
    for item in items[:limit]:
        system_type = str(item.get("type") or "")
        labels.append(TYPE_LABELS.get(system_type, system_type))
    return "、".join(label for label in labels if label)


def _action_hint(target_type: str, level: str | None) -> str:
    if target_type in {"heavy_rain_potential", "heavy_rain_risk"}:
        if level == "high":
            return "建议重点监测雨带落区、短时雨强和中小河流及城市内涝风险，并结合雷达、卫星和自动站实况订正。"
        return "建议继续跟踪低空急流出口、水汽辐合和实况回波发展，防止局地短时强降水漏报。"
    if target_type in {"convection_potential", "convection_risk"}:
        if level == "high":
            return "建议重点关注触发线附近雷暴发展、阵风大风和短时强降水，并结合雷达回波形态滚动订正。"
        return "建议关注低层触发能否突破 CIN，并结合风切变、CAPE 和实况回波判断强对流发生概率。"
    if target_type == "dynamic_lift_potential":
        return "建议结合槽前涡度平流、低层辐合和高空辐散配置，判断上升运动是否持续。"
    return "建议结合实况资料和预报员经验订正自动诊断结论。"


def conclusions_from_chains(evidence_chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conclusions = []
    for chain in evidence_chains:
        target_type = str(chain.get("target_type") or "")
        if target_type == "precipitation_phase":
            continue
        label = _target_label(target_type)
        level = str(chain.get("level") or "low")
        level_text = _level_label(level)
        score_text = _format_score(chain.get("score"))
        reasoning = []
        dominant = chain.get("dominant_evidence") or []
        if dominant:
            reasoning.append(f"主导证据为{_dominant_text(dominant)}。")
        linked = chain.get("linked_systems") or []
        if linked:
            reasoning.append(f"关联天气系统包括{_systems_text(linked)}，说明风险区附近存在可解释的环流和动力支撑。")
        missing = chain.get("missing_evidence") or []
        if missing:
            reasoning.append(f"仍有{len(missing)}个可选证据场缺测，结论可信度需结合实况订正。")

        conclusions.append(
            {
                "id": f"conclusion-{target_type}",
                "target_type": target_type,
                "level": level,
                "score": chain.get("score"),
                "headline": f"{label}为{level_text}，综合评分{score_text}。",
                "reasoning": reasoning,
                "action_hint": _action_hint(target_type, level),
            }
        )
    return conclusions


def conclusions_from_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conclusions = []
    for feature in features:
        props = feature.get("properties") or {}
        target_type = str(props.get("feature_type") or "")
        if target_type not in {"heavy_rain_risk", "convection_risk"}:
            continue
        label = _target_label(target_type)
        level = str(props.get("risk_level") or "moderate")
        level_text = _level_label(level)
        score_text = _format_score(props.get("max_value"))
        reasoning = []
        factors = props.get("dominant_factors") or []
        if factors:
            reasoning.append(f"主导因子为{_dominant_text(factors)}。")
        systems = props.get("supporting_systems") or []
        if systems:
            reasoning.append(f"关联天气系统包括{_systems_text(systems)}，说明潜势区具备空间配合。")
        core_points = int(props.get("core_point_count") or 0)
        if core_points > 0:
            reasoning.append(f"高潜势核心区包含{core_points}个格点，需要优先关注。")

        conclusions.append(
            {
                "id": f"conclusion-{props.get('id') or target_type}",
                "target_type": target_type,
                "level": level,
                "score": props.get("max_value"),
                "headline": f"{label}达到{level_text}潜势，最高评分{score_text}。",
                "reasoning": reasoning,
                "action_hint": _action_hint(target_type, level),
            }
        )
    return conclusions
