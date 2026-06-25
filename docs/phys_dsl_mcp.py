from __future__ import annotations

import os
from typing import Any
from datetime import datetime
import httpx
from fastmcp import FastMCP
from pydantic import Field


mcp = FastMCP(name="nowcasting-physics-dsl-mcp-server")

DEFAULT_API_BASE = "http://127.0.0.1:11011"
DEFAULT_ENDPOINT = "/api/nowcasting/diagnosis"
DEFAULT_TIMEOUT_SECONDS = 180.0
DSL_STRUCTURE_GUIDE = """## DSL 结构

直接阅读接口返回 JSON 中的 DSL 内容，先识别这些语义元素。不要假设它一定存在于某个固定字段名中；以本次响应实际结构为准。

- `@A`：行政区域。
- `@CR`：空间编码规则，当前常见为 `S5=CCCTT;S8=CCCTTSSS;CCC=区县;TT=乡镇/街道;SSS=站点;`。
- `@S`：区县和乡镇映射。解析 S5/S8 名称必须优先用本轮 `@S`，不要另行臆造名称。
- `@PHY_ORD` 和 `@PHY`：物理量字典，定义接口字段、单位、风险方向、关注阈值、高风险阈值。
- `@B`：数据块身份。
- `@M`：模式名，常见于 `FCST_TWN_PHY`，如 `EC`。
- `@T`：实况分析时间或模式起报时间，格式通常为 `YYMMDDHHMM`。
- `@DT`：预报时效，单位分钟，只用于 `FCST_*`。
- `@WIN_RULE`：预报时间解释，如 `VALID=@T+DT`。
- `@ORD`：正文解析顺序。解析 `#PHY` 必须严格按最近的 `@ORD`。
- `#PHY` 或等价正文数据：物理量正文。

物理量字典常见内容：

```text
@PHY_ORD:PID=API|UNIT|DIR|WATCH|HIGH;
@PHY:
CAPE=cape_j_kg|J/kg|gte|1000|2000;
CIN=cin_j_kg|J/kg|lte|150|50;
Q850=q850_g_kg|g/kg|gte|8|12;
MFD700=mfd700|x10^-7_g/(cm2_hPa_s)|lte|0|-10;
OM500=omega500_pa_s|Pa/s|lte|0|-0.2;
SHR6=shear_0_6km_ms|m/s|gte|12|20;
KI=k_index_c|degC|gte|32|38;
SI=si_c|degC|lte|0|-3;
```

`DIR=gte` 表示值越大风险越高，`DIR=lte` 表示值越小风险越高。`WATCH` 是关注阈值，`HIGH` 是高关注阈值。若本轮 DSL 的 `@PHY` 和上面不同，以本轮 DSL 为准。

`NA` 表示缺测、接口未返回或当前对象不适用，不能当成 0，也不能参与阈值判断。

## 块解析

### OBS_STN_PHY

实况站点物理量：

```text
@B:OBS_STN_PHY;
@T:2605150800;
@ORD:S8=CAPE|CIN|Q850|MFD700|OM500|SHR6|KI|SI;
#PHY:12003001=-145|-5|11.95|NA|NA|11|35|1;
```

解析规则：

- `@ORD:S8=...` 表示每条 `#PHY` 是 `S8=物理量值列表`。
- S8 是站点短码；需要名称时按 `@CR` 拆出所属 S5，再用 `@S` 找区县和乡镇。
- 实况用于判断当前环境是否已经具备不稳定、水汽、抬升或切变条件。

### FCST_TWN_PHY

数值预报乡镇物理量，支持多模式、多格点、多时效：

```text
@B:FCST_TWN_PHY;
@M:EC;
@T:2606042000;
@DT:720,900,1080;
@WIN_RULE:VALID=@T+DT;
@ORD:DT>S5=CAPE|CIN|Q850|MFD700|OM500|SHR6|KI|SI;
#PHY:
720>10201=834.16|0|14.27|NA|NA|NA|36.81|NA,...;
900>10201=797|15.64|15.31|NA|NA|NA|35.36|NA,...;
```

解析规则：

- `@ORD:DT>S5=...` 表示先按预报时效 `DT` 分组，再读 `S5=物理量值列表`。
- `DT` 单位是分钟。`720` 是起报后 12 小时，`900` 是 15 小时，`1080` 是 18 小时。
- `@WIN_RULE:VALID=@T+DT` 表示有效时间由起报时间加时效得到；回答中可写“F+12h/720min”，不确定实际北京时间时不要硬换算。
- 多个 `@M` 时先分模式分析，再比较一致信号和分歧信号。
- 不能把所有 `DT`、所有乡镇、所有模式混成一个平均结论。

## 物理量意义

- `CAPE` 高值：不稳定能量更充足。
- `CIN` 低值：抑制弱，更容易触发；高值说明触发受抑。
- `Q850` 高值：低层水汽更充足。
- `MFD700` 负值：中低层水汽辐合信号。
- `OM500` 负值：上升运动信号。
- `SHR6` 高值：组织化对流和雷暴大风环境更有利。
- `KI` 高值、`SI` 低值：对流潜势增强。

短临研判组合：

- 短时强降水环境：`CAPE` 达关注或高关注、`Q850` 较高、`CIN` 弱，同时有 `MFD700` 负值或 `OM500` 负值更有利。
- 雷暴大风或组织化对流环境：`CAPE` 配合 `SHR6` 达关注或高关注更值得关注。
- 触发不确定：`CIN` 偏高、`MFD700/OM500` 缺测或不支持上升时，要降低确定性表述。
- 暖区水汽条件：`Q850` 高但 `CAPE/抬升/切变` 不配合时，只能说水汽条件较好，不能直接说会发生强对流。
- 物理量只代表环境支持度，不能替代雷达、实况降水、闪电、探空、风廓线和预警业务规则。"""


def load_dsl_structure_guide() -> str:
    """返回内置的物理量 DSL 结构说明。"""

    return DSL_STRUCTURE_GUIDE


async def _post_nowcasting_diagnosis(
    payload: dict[str, Any],
    *,
    api_base: str,
    endpoint: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/{endpoint.lstrip('/')}"
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _build_dsl_request_payload(
    *,
    region: str,
    analysis_time: str | None,
    forecast_hours: int,
    models: list[str] | tuple[str, ...] | str | None,
) -> dict[str, Any]:
    return {
        "region": region,
        "analysis_time": analysis_time,
        "forecast_hours": forecast_hours,
        "models": _normalize_models(models),
        "include_dsl": True,
        "include_data_sources": False,
        "include_chart_series": False,
        "include_raw_profiles": False,
    }


def _normalize_models(models: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if models is None:
        return ["EC"]
    if isinstance(models, str):
        return [item.strip() for item in models.split(",") if item.strip()] or ["EC"]
    normalized = [str(item).strip() for item in models if str(item).strip()]
    return normalized or ["EC"]


def _api_base() -> str:
    return os.environ.get("NOWCASTING_PHYS_DSL_API_BASE", DEFAULT_API_BASE).strip() or DEFAULT_API_BASE


def _timeout_seconds() -> float:
    raw_value = os.environ.get("NOWCASTING_PHYS_DSL_TIMEOUT_SECONDS")
    if not raw_value:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS


@mcp.tool
async def get_nowcasting_physics_dsl(
    region: str = Field(default="fuzhou", description="区域编码，默认 fuzhou。"),
    analysis_time: str | None = Field(
        default=None,
        description="分析时间，格式 YYYY-MM-DD HH:MM:SS；为空时由物理量接口按自身策略取时次。",
    ),
    forecast_hours: int = Field(default=6, description="预报时长，单位小时，默认 6。"),
    models: list[str] | None = Field(default=None, description="数值模式列表，默认 ['EC']。"),
) -> dict[str, Any]:
    """获取短临物理量 DSL，并同时返回物理量 DSL 结构解析说明。"""
    if not analysis_time:
        analysis_time = f"{datetime.now().strftime('%Y-%m-%d %H:%M:00')}"
    payload = _build_dsl_request_payload(
        region=region,
        analysis_time=analysis_time,
        forecast_hours=forecast_hours,
        models=models,
    )
    api_base = _api_base()
    timeout_seconds = _timeout_seconds()
    try:
        dsl_response = await _post_nowcasting_diagnosis(
            payload,
            api_base=api_base,
            endpoint=DEFAULT_ENDPOINT,
            timeout_seconds=timeout_seconds,
        )
        api_code = int(dsl_response.get("code", 200)) if isinstance(dsl_response, dict) else 200
        return {
            "code": api_code,
            "msg": dsl_response.get("msg", "success") if isinstance(dsl_response, dict) else "success",
            "data": {
                "request_payload": payload,
                "api_base": api_base,
                "endpoint": DEFAULT_ENDPOINT,
                "dsl_response": dsl_response,
                "dsl_structure_guide": load_dsl_structure_guide(),
            },
        }
    except Exception as exc:
        return {
            "code": 500,
            "msg": f"获取物理量 DSL 失败: {exc}",
            "data": {
                "request_payload": payload,
                "api_base": api_base,
                "endpoint": DEFAULT_ENDPOINT,
                "dsl_structure_guide": load_dsl_structure_guide(),
            },
        }


def main() -> None:
    host = os.environ.get("NOWCASTING_PHYS_DSL_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("NOWCASTING_PHYS_DSL_MCP_PORT", "11012"))
    path = os.environ.get("NOWCASTING_PHYS_DSL_MCP_PATH", "/messages")
    transport = os.environ.get("NOWCASTING_PHYS_DSL_MCP_TRANSPORT", "http")
    mcp.run(transport=transport, host=host, port=port, path=path)


if __name__ == "__main__":
    main()
