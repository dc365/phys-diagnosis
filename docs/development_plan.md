# 开发计划

## 阶段 1：真实数据适配

- 获取 EC NetCDF 样例
- 运行 `scripts/inspect_netcdf.py`
- 修改 `configs/models/ecmwf.yaml`
- 跑通 `diagnose`

## 阶段 2：算法校验

- 对比 MetPy 或业务平台的散度/涡度/水汽通量
- 选 3 个历史个例调阈值
- 优化强降水/强对流评分

## 阶段 3：GIS 增强

- MapLibre 地图底座已落地，继续完善图层管理
- 增加瓦片、COG 或 PMTiles 服务
- 增加等值线绘制
- 增加风羽/流线
- 预留三维地形或 Cesium 场景入口

## 阶段 4：业务增强

- 人工编辑锋面/槽线
- 模式对比
- 报告导出
- AI 写稿接口
