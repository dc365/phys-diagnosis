# Linux conda 环境重建说明

这份说明基于当前工作区的 `.venv` 导出，导出时间为 2026-06-22。

- 当前 Python 版本：3.13.12
- 导出方式：读取当前 `.venv` 中已安装的实际包版本
- 目标：在 Linux 上用 conda 新建一个尽量贴近当前 `.venv` 的环境

## 直接创建

在 Linux 机器上进入项目根目录后执行：

```bash
conda env create -f environment.linux-conda.yml
conda activate phys-diagnosis-linux
```

如果环境已经存在，改用：

```bash
conda env update -f environment.linux-conda.yml --prune
conda activate phys-diagnosis-linux
```

## 校验

先确认 Python 版本和核心依赖：

```bash
python -V
python -c "import fastapi, xarray, netCDF4, numpy, scipy, pandas, matplotlib, shapely; print('imports ok')"
```

再跑一组项目测试做烟雾验证：

```bash
pytest tests/test_public_api.py tests/test_diagnostics.py
```

## 说明

- `environment.linux-conda.yml` 里使用的是精确版本，目的是尽量复刻当前 `.venv`。
- 这个文件把 conda 作为环境管理器，Python 包安装交给 `pip`，这样最接近当前环境实际状态。
- 其中 `httpx2` 和 `httpcore2` 这类包保留为 `pip` 安装项，不强行映射成 conda 包。
- 由于当前环境来自 macOS 的 `.venv`，在 Linux 上虽然包版本可以对齐，但底层二进制和系统库不一定完全一致。

## 如果严格复刻失败

如果 Linux 上某些精确版本拉不下来，优先退一步，用项目声明依赖重建：

```bash
conda create -n phys-diagnosis-linux python=3.13 -y
conda activate phys-diagnosis-linux
pip install -r backend/requirements.txt
pip install pytest
```

如果你更想让 conda 接管科学计算栈，可以先装这些常见二进制依赖：

```bash
conda install -c conda-forge numpy scipy pandas xarray netcdf4 h5netcdf matplotlib shapely pyyaml
pip install -r backend/requirements.txt
pip install pytest
```

第二种方案不保证与当前 `.venv` 完全一致，但通常在 Linux 上更稳。