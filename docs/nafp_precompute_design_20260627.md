# NAFP 数值预报诊断预计算设计

本次改造把天气系统和风险诊断从“地图点击时即时计算”改为“后端预计算、前端读取结果”。

## 目标

- 后端启动后自动为最新 NAFP 起报时次预计算诊断结果。
- 预计算进度和历史结果可在后台页面查看。
- 支持手动点击重新计算，可选择时效并强制覆盖已有结果。
- MapLibre 地图加载天气系统对象时不再触发同步诊断计算，只读取预计算结果。

## 后端结构

### `weather_diag/diagnosis/nafp_precompute.py`

负责预计算任务管理：

- 后台线程执行预计算；
- 任务状态持久化到 `data/admin/nafp_precompute/state.json`；
- 每个时效结果持久化到 `data/admin/nafp_precompute/results/...json`；
- 支持命中已有结果、强制重算、失败记录、进度统计；
- 服务启动时可自动为最新起报时次创建预计算任务。

可用环境变量：

```text
WEATHER_DIAG_AUTO_PRECOMPUTE=1       # 默认开启；设为 0/false/no 可关闭
WEATHER_DIAG_PRECOMPUTE_MAX_HOURS=999 # 限制自动预计算时效个数
```

### `backend/app/api/v1/precompute.py`

新增接口：

```text
GET  /api/v1/diagnosis/nafp/precompute/status
POST /api/v1/diagnosis/nafp/precompute
POST /api/v1/diagnosis/nafp/precompute/run
GET  /api/v1/diagnosis/nafp/precompute/result
GET  /api/v1/diagnosis/nafp/precompute/features
GET  /api/v1/diagnosis/nafp/precompute/ready
```

其中 `/features` 只读取预计算结果；如果结果不存在，会排队一个单时效任务并返回 409，不会在地图请求线程里重复计算。

### `backend/app/main.py`

- 在 legacy diagnosis router 前注册 precompute router；
- 启动时调用 `autostart_precompute_for_latest(...)`。

## 前端结构

### `frontend/precompute-map-extension.js`

在 `maplibre-utils.js` 之后、`map.js` 之前加载，覆盖：

```text
WeatherMapUtils.buildNafpFeaturesUrl
```

使地图天气系统对象请求改到：

```text
/api/v1/diagnosis/nafp/precompute/features
```

### `frontend/precompute.html`

独立后台预计算监控页面，可通过：

```text
/static/precompute.html
```

打开。功能包括：

- 查看最新任务状态、进度、结果文件数；
- 查看最近任务列表和各时效计算结果；
- 手动提交预计算；
- 强制重新计算。

## 地图行为

旧行为：

```text
点击天气系统复选框 -> /diagnosis/nafp/features -> 若缓存没有则同步计算
```

新行为：

```text
后端自动或手动预计算 -> 持久化结果
点击天气系统复选框 -> /diagnosis/nafp/precompute/features -> 只读取结果
```

当结果尚未准备好时，接口返回 409 并自动排队单时效任务。用户稍后刷新或等待后台任务完成后即可加载。

## 后续建议

- 将 `/static/precompute.html` 合入主后台“服务状态”页面；
- 给预计算任务增加取消按钮；
- 增加定时扫描新起报时次的后台 scheduler；
- 将区域风险也改成读取预计算 result，避免区域风险查询触发隐式诊断。
