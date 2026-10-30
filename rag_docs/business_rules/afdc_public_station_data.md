# AFDC 加州公开电动汽车充电站数据

"
        f"> 本文是 ChargeOps 对公开数据快照的登记说明，不是政策或建设审批结论。

"
        f"## 数据来源

"
        f"- 提供方：美国能源部 Alternative Fuels Data Center（AFDC），数据由 National Laboratory of the Rockies 维护。
"
        f"- 下载接口：https://developer.nlr.gov/api/alt-fuel-stations/v1.csv?api_key=DEMO_KEY&fuel_type=ELEC&access=public&status=E&state=CA&limit=all
"
        f"- 数据说明：https://afdc.energy.gov/data_download
"
        f"- 字段参考：https://afdc.energy.gov/data_download/alt_fuel_stations_format
"
        f"- 查询条件：燃料类型 `ELEC`、`public`、状态 `E`（Open）、区域 `CA`、当前快照。
"
        f"- ChargeOps 下载时间：2026-10-29（America/Los_Angeles）。
"
        f"- 原始文件：`data/raw/public/afdc_electric_stations_ca_2026-10-29.csv`。
"
        f"- SHA-256：`06a32bcf522dca77910eb264eb1fea5d9dc6888e8ccdd6c777e6607dbf41020d`。
"
        f"- 使用条款：AFDC 数据下载页声明数据可用于任何目的，但按“现状”提供，使用者需遵守其免责声明和署名限制。

"
        f"## 快照概况

"
        f"- 区域：California（`CA`）
"
        f"- 公开且开放的电动汽车站点：20,369 个
"
        f"- 连接器数量（按 Level 1、Level 2、DC Fast 和 Other 字段求和）：69,599 个
"
        f"- 坐标有效率：100.00%
"
        f"- 主要网络：
- ChargePoint Network: 14,542 个站点
- Tesla: 698 个站点
- Non-Networked: 648 个站点
- Blink Network: 601 个站点
- LOOP: 591 个站点
- Tesla Destination: 590 个站点
- FLO: 436 个站点
- eVgo Network: 396 个站点
- Electrify America: 331 个站点
- EVCS: 194 个站点

"
        f"## ChargeOps 业务映射

"
        f"| AFDC 字段 | ChargeOps 字段 | 说明 |
|---|---|---|
"
        f"| `ID` | `charging_station.external_station_id` | AFDC 外部站点主键 |
"
        f"| `Station Name` | `charging_station.station_name` | 站点名称 |
"
        f"| `Latitude` / `Longitude` | `charging_station.latitude` / `longitude` | 地理坐标 |
"
        f"| `EV Network` | `operator.operator_name` | 空值统一为 `Non-Networked` |
"
        f"| `EV Level1 EVSE Num` | `charging_connector(LEVEL1).quantity` | Level 1 数量 |
"
        f"| `EV Level2 EVSE Num` | `charging_connector(LEVEL2).quantity` | Level 2 数量 |
"
        f"| `EV DC Fast Count` | `charging_connector(DC_FAST).quantity` | 直流快充数量 |
"
        f"| `Status Code` / `Access Code` | 站点状态与访问属性 | 只导入当前公开开放快照 |

"
        f"所有业务记录写入 `source_type=public`，并关联导入批次、原始文件、来源 URL 和快照版本。

"
        f"## 使用限制

"
        f"该数据描述公开站点基础设施，不包含 ChargeOps 所需的真实订单、利用率、故障、预算或电力容量。Agent 不得仅凭本快照生成投资、审批或扩容批准结论。
