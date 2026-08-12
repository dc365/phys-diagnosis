区域气象探空基础要素下载说明

数据源: University of Wyoming Atmospheric Science Radiosonde Archive
范围: 5N-55N, 50E-160E 区域探空站
经纬度框: 5.0N-55.0N, 50.0E-160.0E
下载目录: regional_radiosonde_5N55N_50E160E_20260624_20260625
时间选择: 数据抓取使用最近两个完整 UTC 日的标准探空时次 00Z/12Z，站点范围为 5N-55N、50E-160E，输出时间统一转换为北京时间
时次: 2026-06-24 08:00:00, 2026-06-24 20:00:00, 2026-06-25 08:00:00, 2026-06-25 20:00:00
站点并集数量: 231
层次选择: 地面层 + 1000/950/925/850/800/750/700/600/500/400/300/250/200/150/100hPa
选层方法: 对每个目标气压层，从原始探空剖面中选取 pressure_hpa 最接近的一条记录。
站名说明: 中国站优先使用中文名，非中国站保留资料源原始站名。
文件说明:
- regional_radiosonde_5N55N_50E160E_YYYYMMDD_HHBJT.csv: 单个时次下全部区域站的指定层次基础要素合并表，文件名时间为北京时间
- stations_manifest.csv: 站点清单，附英文原名供核对，时次字段为北京时间
- download_report.json: 每个时次的站点数、行数、缺测站列表
字段说明:
- request_datetime_bjt, requested_level, station_id, station_name, station_lat, station_lon, station_src
- observation_time_bjt, obs_longitude, obs_latitude, pressure_hpa, geopotential_height_m
- temperature_c, dew_point_temperature_c, ice_point_temperature_c
- relative_humidity_pct, humidity_wrt_ice_pct, mixing_ratio_g_per_kg, wind_direction_degree, wind_speed_m_s