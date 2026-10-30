# AFDC 充电站字段字典摘录

"
        f"来源：[https://afdc.energy.gov/data_download/alt_fuel_stations_format](https://afdc.energy.gov/data_download/alt_fuel_stations_format)。本摘录服务于 ChargeOps 首批加州公开站点导入。

"
        f"| 字段 | 类型 | 用途 |
|---|---|---|
"
        f"| `ID` | integer | 外部站点主键，导入时保留 |
"
        f"| `Station Name` | string | 站点名称 |
"
        f"| `Street Address`, `City`, `State`, `ZIP` | string | 地址 |
"
        f"| `Latitude`, `Longitude` | number | 站点坐标；必须校验范围 |
"
        f"| `Status Code` | string | 站点状态，`E` 表示 Open |
"
        f"| `Access Code` | string | 访问属性，`public` 表示公开 |
"
        f"| `EV Network` | string | 运营网络名称 |
"
        f"| `EV Level1 EVSE Num` | integer | Level 1 充电端口数 |
"
        f"| `EV Level2 EVSE Num` | integer | Level 2 充电端口数 |
"
        f"| `EV DC Fast Count` | integer | DC Fast 端口数 |
"
        f"| `EV Connector Types` | string | 原始连接器类型列表，保留原值 |
"
        f"| `Date Last Confirmed`, `Updated At` | date/datetime | 数据时效性判断 |

"
        f"原始 CSV 不覆盖、不改写；清洗后的统一字段写入 `data/processed/`。
