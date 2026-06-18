# 数据契约

## 输入

NetCDF 必须包含：

- lat/lon 或 latitude/longitude
- forecast_hour/step/leadtime 之一，或单一时效
- level/pressure_level/isobaricInhPa 之一，若变量为气压层变量

## 建议变量

- mslp/msl
- z 或 gh
- t
- u/v
- q
- r/rh
- w/omega
- tp/precip
- cape/cin
- t2m/d2m/u10/v10

## 单位

系统会尝试自动转换：

- Pa → hPa
- K → ℃
- m → mm
- geopotential m²/s² → gpm

真实数据接入后，需检查转换是否符合实际文件元数据。
