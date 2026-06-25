# 天气形势分析与物理量诊断工作台

这是一个天气形势分析与物理量诊断工程，用于基于 **ECMWF/EC 模式 NetCDF 格点数据**进行：

- NetCDF 数据读取与变量标准化
- 常用气象物理量诊断计算
- 高压、低压、槽脊、副高、辐合区、辐散区、低空急流、水汽输送带、锋面候选区自动识别
- 六类风险格点评分：持续性强降水、短时强降水、雷暴大风、冰雹、旋转风暴/超级单体潜势、强对流综合风险
- Web 端 MapLibre GIS 可视化
- 自动天气形势分析文本生成

> 当前版本没有绑定真实 EC 文件变量结构。系统使用 `configs/models/ecmwf.yaml` 做变量映射，并内置 `generate-demo` 示例数据，便于先跑通完整闭环。拿到真实 EC NetCDF 后，优先调整变量映射和单位转换。

## 目录结构

```text
weather_diagnosis_mvp/
├── backend/                 # FastAPI 服务入口
├── weather_diag/            # 数据读取、诊断算法、天气系统识别、分析文本
├── frontend/                # 无构建依赖的 MapLibre Web GIS 页面
├── configs/                 # 模式变量映射、阈值、图层配置
├── data/                    # raw/products 示例数据和产品输出目录
├── docs/                    # 需求、接口、算法、Codex 规则
├── tests/                   # 基础测试
├── scripts/                 # 命令行工具
└── docker-compose.yml
```

## 快速开始

### 1. 创建环境

```bash
cd weather_diagnosis_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. 启动后台整体服务

```bash
scripts/services.sh start
```

该脚本会在后台启动：

- `api`：FastAPI 工作台服务，默认 `http://localhost:8000`
- `area-risk-mcp`：风险 MCP 服务，默认 `http://localhost:11011/mcp`，默认传输方式为 HTTP；包含 `get_town_risk_dsl`（乡镇风险 DSL）和 `get_point_risk`（经纬度点风险 JSON）

浏览器打开：

```text
http://localhost:8000
```

常用运维命令：

```bash
scripts/services.sh status
scripts/services.sh restart
scripts/services.sh restart area-risk-mcp
scripts/services.sh logs api
scripts/services.sh stop
```

PID 和日志默认写入 `.runtime/pids`、`.runtime/logs`。需要改端口或主机时可用环境变量覆盖：

```bash
WEATHER_DIAG_API_PORT=8001 AREA_RISK_DSL_MCP_PORT=11012 scripts/services.sh restart
```

如果只想前台调试 API，也可以继续使用：

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 生成示例 EC NetCDF 数据

```bash
curl -X POST http://localhost:8000/api/jobs/generate-demo
```

也可以用脚本：

```bash
python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc
```

### 4. 执行诊断

```bash
curl -X POST "http://localhost:8000/api/jobs/diagnose?model=ecmwf&file_path=data/raw/ecmwf_demo.nc&run_id=ecmwf_demo"
```

### 对外服务 API 示例

第三方系统建议使用 `/api/v1` 接口，响应统一为 `code/msg/data/trace_id`：

```bash
curl -F "file=@data/raw/ecmwf_demo.nc" http://localhost:8000/api/v1/files/upload
```

也可以直接引用服务端已有文件提交诊断任务：

```bash
curl -X POST http://localhost:8000/api/v1/jobs/diagnose \
  -H "Content-Type: application/json" \
  -d '{"model":"ecmwf","file_path":"data/raw/ecmwf_demo.nc","run_id":"ecmwf_demo"}'
```

查询诊断产物索引：

```bash
curl http://localhost:8000/api/v1/runs/ecmwf_demo
```

### 5. 查看结果

前端会自动读取 `ecmwf_demo` 的产品。也可以访问：

```text
http://localhost:8000/api/analysis/situation?run_id=ecmwf_demo&forecast_hour=24
http://localhost:8000/api/features?run_id=ecmwf_demo&forecast_hour=24
http://localhost:8000/api/layers/z500/grid?run_id=ecmwf_demo&forecast_hour=24
```

## 第一版已实现内容

### 数据模块

- 自动读取 NetCDF
- 变量名映射配置
- 常见单位转换：Pa→hPa、K→℃、m→mm、geopotential→gpm
- 经纬度维度标准化
- 预报时效识别

### 物理量诊断

- 风速、风向
- 散度/辐合
- 相对涡度/垂直涡度
- 涡度平流
- 温度平流
- 水汽通量
- 水汽通量散度/水汽辐合
- K 指数
- 0–6 km 深层风切变近似
- 持续性强降水风险评分
- 短时强降水风险评分
- 雷暴大风/下击暴流风险评分
- 冰雹风险评分
- 旋转风暴/超级单体潜势评分
- 强对流综合风险评分

### 天气系统识别

- 高压中心
- 低压中心
- 副高 5880gpm 区域
- 500hPa 槽线候选
- 500hPa 脊线候选
- 850hPa 低层辐合区
- 200/300hPa 高空辐散区
- 850hPa 低空急流
- 850hPa 水汽输送带
- 锋面候选区
- 强降水潜势区
- 强对流潜势区

### Web 可视化

- MapLibre GL JS 地图底座
- 地图主工作台布局，支持模式/运行、要素、预报时效时间轴
- 图层开关
- 诊断格点以 GeoJSON GIS 图层着色
- GeoJSON 天气系统图层叠加
- 时间时效选择
- 点击对象查看证据
- 自动形势分析面板

## 重要说明

1. **锋面、槽线、脊线当前均为候选识别。** 它们依赖分辨率、区域、季节和模式偏差，需要历史个例调参。
2. **第一版为可解释规则算法。** 暂未使用深度学习。
3. **所有阈值应随业务区域配置。** 见 `configs/thresholds.yaml`。
4. **真实 EC 文件接入后，第一步是生成数据解析报告。** 可运行：

```bash
python scripts/inspect_netcdf.py data/raw/your_ec_file.nc
```

## 后续建议

- 接入真实 EC 样例后优化变量映射
- 用暴雨、强对流、冷空气个例验证阈值
- 将诊断栅格升级为瓦片、COG 或 PMTiles 服务
- 增加等值线绘制和三维地形/场景预留
- 引入 PostGIS 持久化
- 引入异步任务队列
- 加入雷达、卫星、自动站实况订正
# phys-diagnosis
