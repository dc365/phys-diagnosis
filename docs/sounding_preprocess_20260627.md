# 实况探空站预处理设计

本次把探空站实况资料纳入统一预处理链路，并在后台“数据字段”页面显示质量控制结果。

## 预处理目标

探空资料用于 500hPa 实况天气图、H/L/W/C 中心、槽线/切变线和站点风险诊断。原始 CSV 直接进入客观分析会有两个问题：

- 个别异常站点高度可能导致 500hPa 等值线出现不合理密集闭合；
- 缺测、重复、层次不完整、露点高于温度、风速风向异常等会影响站点诊断和 MetPy 指数。

因此新增预处理链路：

```text
CSV 原始探空
  -> 字段标准化
  -> 数值和单位规范化
  -> 经纬度/层次/温湿风范围检查
  -> 露点 <= 温度约束
  -> 重复站-时次-层次去重
  -> 500hPa 高度 buddy check
  -> 标准层覆盖率统计
  -> 清洗 CSV + JSON 报告
  -> sounding_optimized 优先读取清洗 CSV
```

## 后端模块

### `weather_diag/diagnosis/sounding_preprocess.py`

主要能力：

- 自动发现 `test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625` 下的 CSV；
- 支持字段别名归一；
- 输出 `qc_flags` 和 `qc_status`；
- 输出清洗后的 CSV；
- 输出预处理报告 JSON；
- 统计站点数、标准层覆盖率、弱廓线站点数、剔除原因分布。

输出位置：

```text
data/admin/sounding_preprocess/cleaned/*.clean.csv
data/admin/sounding_preprocess/reports/*.preprocess.json
data/admin/sounding_preprocess/state.json
```

### `backend/app/api/v1/sounding_preprocess.py`

新增接口：

```text
GET  /api/v1/sounding/preprocess/status
POST /api/v1/sounding/preprocess/run
GET  /api/v1/sounding/preprocess/report
GET  /api/v1/sounding/preprocess/files
```

## 运行时集成

`weather_diag/diagnosis/sounding_optimized.py` 现在会先调用预处理模块：

```text
sounding_optimized.diagnose_sounding_situation(csv)
  -> preprocess_sounding_csv(csv)
  -> 使用 cleaned_csv_path 继续 Barnes 客观分析和系统识别
```

如果预处理失败，会回退到原始 CSV，并在 `preprocess_report` 中返回错误信息。

## 后台 UI

新增：

```text
frontend/sounding-preprocess-admin-extension.js
```

该脚本由后台首页 `/` 自动注入，挂载到：

```text
#data-fields .data-grid
```

后台“数据字段”页面会显示：

- 可用探空 CSV 文件；
- 单文件预处理；
- 全部预处理；
- 强制重跑；
- 通过/剔除行数；
- 站点数；
- 弱廓线站点数；
- 标准层覆盖率；
- 各类 QC 剔除原因。

## 关键 QC 规则

- 经纬度范围检查；
- 气压 50–1100hPa；
- 温度 -100–60℃；
- 露点 -120–50℃；
- 露点不能明显高于温度；
- 位势高度 -500–35000m；
- 风向 0–360°；
- 风速 0–150m/s；
- 500hPa 高度硬范围和 buddy check；
- `station_id + observation_time + requested_level` 重复去重；
- 标准层覆盖率与弱廓线统计。

## 后续建议

- 增加 BUFR/TEMP 报文解析入口；
- 将预处理报告纳入 API 响应的质量摘要；
- 增加跨时次站点漂移检查；
- 增加 500hPa 高度与 EC 分析场 first guess 的偏差检查；
- 将 QC 参数纳入算法治理阈值矩阵。
