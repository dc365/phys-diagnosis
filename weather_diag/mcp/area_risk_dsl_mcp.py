from __future__ import annotations

import os
from typing import Annotated, Any

from pydantic import Field

from weather_diag.mcp.area_risk_dsl import AREA_RISK_DSL_STRUCTURE_GUIDE, get_town_risk_dsl_payload
from weather_diag.mcp.observed_sounding import get_observed_sounding_payload
from weather_diag.mcp.point_risk import POINT_RISK_RESPONSE_GUIDE, get_point_risk_payload

try:
    from fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - runtime dependency guard
    FastMCP = None  # type: ignore[assignment]


mcp = FastMCP(name="town-risk-dsl-mcp-server") if FastMCP is not None else None


def _optional_run_time(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_town_risk_dsl(
    region: Annotated[str, Field(description="区域编码或别名，支持 fuzhou/xiamen，默认 xiamen。")] = "xiamen",
    start_time: Annotated[
        str | None,
        Field(description="开始有效时间，ISO 格式或 YYYY-MM-DD HH:MM:SS；为空时取当前系统时间。"),
    ] = None,
    end_time: Annotated[
        str | None,
        Field(description="结束有效时间，ISO 格式或 YYYY-MM-DD HH:MM:SS；为空时取开始时间 +6 小时。"),
    ] = None,
    models: Annotated[str, Field(description="模式名，逗号分隔，默认 EC。")] = "EC",
    data_code: Annotated[
        str | None,
        Field(description="可选数据源编码；默认按 models 解析，EC 对应 NAFP_ECTHIN_NC。"),
    ] = None,
    windows: Annotated[
        str | dict[str, Any] | list[Any] | None,
        Field(description="Optional multi-window JSON array. Omit to keep legacy single-window response."),
    ] = None,
    time_match_policy: Annotated[
        str | None,
        Field(description="Time matching policy: single_latest_run, fixed_run, or latest_per_valid_time."),
    ] = None,
    run_time: Annotated[
        str | None,
        Field(description="Optional forecast run time. Required when time_match_policy is fixed_run."),
    ] = None,
    include_window_summary: Annotated[
        bool,
        Field(description="Whether multi-window mode emits risk and physical summary DSL sections."),
    ] = True,
) -> dict[str, Any]:
    """返回指定区域所有乡镇的六类风险值、证据物理量字段和 FCST_TWN_PHY DSL 自说明。"""
    try:
        payload = get_town_risk_dsl_payload(
            region=region,
            start_time=start_time,
            end_time=end_time,
            models=models,
            data_code=data_code,
            run_time=_optional_run_time(run_time),
            windows=windows,
            time_match_policy=time_match_policy,
            include_window_summary=include_window_summary,
        )
        return {"code": 0, "msg": "success", "data": payload}
    except Exception as exc:
        return {
            "code": 500,
            "msg": f"获取乡镇风险 DSL 失败: {exc}",
            "data": {"error": str(exc), "dsl_structure_guide": AREA_RISK_DSL_STRUCTURE_GUIDE},
        }


def get_point_risk(
    points: Annotated[
        str | dict[str, Any] | list[Any],
        Field(description="点位列表。支持 JSON 数组，如支持 'lat,lon;lat,lon'。"),
    ],
    start_time: Annotated[
        str | None,
        Field(description="开始有效时间，ISO 格式或 YYYY-MM-DD HH:MM:SS；为空时取当前系统时间。"),
    ] = None,
    end_time: Annotated[
        str | None,
        Field(description="结束有效时间，ISO 格式或 YYYY-MM-DD HH:MM:SS；为空时取开始时间 +6 小时。"),
    ] = None,
    models: Annotated[str, Field(description="模式名，逗号分隔，默认 EC。")] = "EC",
    data_code: Annotated[
        str | None,
        Field(description="可选数据源编码；默认按 models 解析，EC 对应 NAFP_ECTHIN_NC。"),
    ] = None,
    windows: Annotated[
        str | dict[str, Any] | list[Any] | None,
        Field(description="Optional multi-window JSON array. Omit to keep legacy single-window response."),
    ] = None,
    time_match_policy: Annotated[
        str | None,
        Field(description="Time matching policy: single_latest_run, fixed_run, or latest_per_valid_time."),
    ] = None,
    run_time: Annotated[
        str | None,
        Field(description="Optional forecast run time. Required when time_match_policy is fixed_run."),
    ] = None,
    include_window_summary: Annotated[
        bool,
        Field(description="Whether multi-window mode emits risk and physical summary arrays."),
    ] = True,
) -> dict[str, Any]:
    """返回一个或多个经纬度点的六类风险评分、风险证据链和原始物理量证据，非 DSL 格式。"""
    try:
        payload = get_point_risk_payload(
            points=points,
            start_time=start_time,
            end_time=end_time,
            models=models,
            data_code=data_code,
            run_time=_optional_run_time(run_time),
            windows=windows,
            time_match_policy=time_match_policy,
            include_window_summary=include_window_summary,
        )
        return {"code": 0, "msg": "success", "data": payload}
    except Exception as exc:
        return {
            "code": 500,
            "msg": f"获取点风险失败: {exc}",
            "data": {"error": str(exc), "response_guide": POINT_RISK_RESPONSE_GUIDE},
        }


def get_observed_sounding(
    station_code: Annotated[
        str | None,
        Field(description="福建实况探空站号，支持 58847（福州站）、59134（厦门站）、58725（南平邵武站）；为空返回全部支持站点，多个用逗号分隔。"),
    ] = None,
    observation_time: Annotated[
        str | None,
        Field(description="实况探空时间，支持 ISO 或 YYYY-MM-DD HH:MM[:SS]；为空时自动取最新 08/20 时实况。"),
    ] = None,
) -> dict[str, Any]:
    """返回福建实况探空站资料、物理量证据链和天气诊断描述。"""
    try:
        payload = get_observed_sounding_payload(station_code=station_code, observation_time=observation_time)
        return {"code": 0, "msg": "success", "data": payload}
    except Exception as exc:
        return {
            "code": 500,
            "msg": f"获取实况探空站资料失败: {exc}",
            "data": {"error": str(exc)},
        }


if mcp is not None:
    mcp.tool()(get_town_risk_dsl)
    mcp.tool()(get_point_risk)
    mcp.tool()(get_observed_sounding)


def main() -> None:
    if mcp is None:
        raise SystemExit("fastmcp is required to run this MCP server. Install backend requirements first.")
    transport = os.environ.get("AREA_RISK_DSL_MCP_TRANSPORT", "http").strip() or "stdio"
    host = os.environ.get("AREA_RISK_DSL_MCP_HOST", "0.0.0.0").strip() or "127.0.0.1"
    port = int(os.environ.get("AREA_RISK_DSL_MCP_PORT", "11012"))
    path = os.environ.get("AREA_RISK_DSL_MCP_PATH", "/mcp").strip() or "/mcp"
    if transport == "stdio":
        mcp.run(transport=transport)
    else:
        mcp.run(transport=transport, host=host, port=port, path=path)


if __name__ == "__main__":
    main()
