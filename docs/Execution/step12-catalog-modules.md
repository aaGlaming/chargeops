# Step 12：实现区域、运营商、站点和连接器模块

## 目标

在认证和权限基础上，提供区域、运营商、充电站和连接器的统一查询接口，支持分页、筛选、地图点位、详情和来源追溯。

## 已完成内容

### 区域

- `GET /regions`：分页查询区域，可按 `region_code` 筛选。
- `GET /regions/{region_code}`：区域详情、层级字段、边界字段和子区域列表。
- 返回区域站点数量、来源类型、来源 URL/文件、数据版本和导入批次。

### 运营商

- `GET /operators`：分页查询运营商，可按名称模糊筛选。
- `GET /operators/{operator_id}`：运营商详情和关联站点预览。
- 返回运营商代码、网站、站点数量和来源信息。

### 充电站

- `GET /stations`：分页查询站点。
- 支持区域、运营商、站点状态、访问类型、充电类型、来源类型和数据版本筛选。
- 支持经纬度边界框和中心点半径筛选，半径使用 MySQL 球面距离计算。
- `GET /stations/{station_id}`：站点详情、区域、运营商、连接器和运营指标/故障/Agent/扩容关联入口。
- 所有站点列表和详情都返回 `source_type`、来源 URL/文件、数据版本和导入批次。

### 连接器

- `GET /connectors`：按站点、连接器类型、连接器状态、来源和版本查询。
- `GET /stations/{station_id}/connectors`：查询指定站点连接器。
- 返回连接器类型、数量、功率、状态和来源标签；当前历史兼容表缺失功率/状态时返回 `null`。

### 地图

- `GET /stations/map-points`：返回批量地图点位，默认最多 5,000 个，可调整到 10,000。
- `GET /stations/{station_id}/map-point`：返回单个站点点位详情。
- 点位包含坐标、站点状态、访问类型、连接器数量、区域、运营商、来源类型和数据版本。

## 兼容现有数据

Step 9 已导入的本地数据库保留了早期字段名，例如 `status_code`、`access_code`、`country` 和 `ev_connector_types`。目录服务在查询时根据实际表字段映射为统一 API 字段 `station_status`、`access_type`、`country_code` 和 `charging_types`，目标 DDL 的字段名也可以直接工作。

## 权限

所有目录接口要求当前用户拥有 `station.read` 权限。权限拒绝会返回统一 403 错误并写入 `audit_log`。

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/regions` | 区域列表 |
| `GET` | `/regions/{region_code}` | 区域详情和子区域 |
| `GET` | `/operators` | 运营商列表 |
| `GET` | `/operators/{operator_id}` | 运营商详情和站点关联 |
| `GET` | `/stations` | 站点分页、筛选 |
| `GET` | `/stations/{station_id}` | 站点详情 |
| `GET` | `/connectors` | 连接器分页、筛选 |
| `GET` | `/stations/{station_id}/connectors` | 站点连接器 |
| `GET` | `/stations/map-points` | 批量地图点位 |
| `GET` | `/stations/{station_id}/map-point` | 单个地图点位 |

## 验证记录

使用现有公开数据验证：

- 区域：1 个 `CA` 区域，HTTP 200。
- 运营商：`ABM` 模糊查询，HTTP 200。
- 站点：公开数据返回 20,369 个站点，分页和来源标签正常。
- 连接器：站点详情和连接器列表 HTTP 200。
- 地图：公开站点地图点位 HTTP 200。
- 运营商详情和区域详情 HTTP 200。
- 半径查询 `latitude=34.05&longitude=-118.25&radius_km=10` HTTP 200；缺少中心点时返回 `INVALID_STATION_FILTER`。
- 站点详情包含运营指标、故障、Agent 运行和扩容方案关联入口。

## 产物

- `backend/app/schemas/catalog.py`
- `backend/app/services/catalog.py`
- `backend/app/api/routes/catalog.py`

