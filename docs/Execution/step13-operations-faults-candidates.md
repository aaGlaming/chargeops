# Step 13：实现运营指标、故障和候选站点模块

## 目标

在站点目录和权限基础上，提供运营指标、故障事件和候选站点的查询与管理能力，并用确定性规则判断候选站点是否可评估、是否允许进入推荐状态。

## 已完成内容

### 运营指标

- `GET /metrics`：按站点、日期区间、小时、来源和数据版本分页查询。
- `GET /stations/{station_id}/metrics`：查询指定站点的日/小时指标。
- 返回充电次数、电量、峰值功率、占用率、平均时长、时区、数据日期和来源信息。

### 故障事件

- `GET /faults` 和 `GET /stations/{station_id}/faults`：按站点、状态、严重等级、开始时间、来源和版本筛选。
- `POST /stations/{station_id}/faults`：创建故障事件，校验站点、时间顺序、数据范围和写入权限。
- `PATCH /faults/{fault_id}`：更新严重等级、恢复时间、影响连接器、根因和状态。
- 写入故障时自动将状态设置为 `OPEN` 或 `RECOVERED`；恢复时间不能早于开始时间。
- 创建和更新操作写入 `audit_log`。

### 候选站点

- `GET /candidate-sites`：分页查询候选点，支持区域、生命周期、数据状态和来源筛选。
- `POST /candidate-sites`：创建候选站点。
- `GET /candidate-sites/{candidate_id}`：返回详情、区域、周边站点、政策条件和关联统计。
- `PATCH /candidate-sites/{candidate_id}`：编辑坐标、面积、车位、电力容量、预算、交通和人口指标等字段。
- `POST /candidate-sites/{candidate_id}/status`：管理 `DRAFT`、`REVIEW`、`RECOMMENDED`、`ARCHIVED` 状态。
- `DELETE /candidate-sites/{candidate_id}`：软删除候选站点。

### 完整度和时效性

候选站点服务对以下关键字段执行确定性检查：

- 区域
- 经纬度
- 面积
- 停车位
- 电力容量
- 预算
- 交通指数
- 人口密度
- 计划开放日期

返回：

- `completeness.score`
- `completeness.missing_fields`
- `completeness.evaluable`
- `freshness.data_as_of`
- `freshness.age_days`
- `freshness.status`：`CURRENT`、`STALE` 或 `UNKNOWN`
- `completeness.recommendable`

缺少关键字段或数据过期时，候选站点会标记为不可评估；进入 `RECOMMENDED` 状态的请求会返回 `CANDIDATE_NOT_EVALUABLE`。

### 关联查询

候选站点详情会返回：

- 25 公里范围内的周边充电站。
- 同区域政策条件、版本、生效日期、申请截止日期和来源信息。
- 周边站点数量、政策数量和区域详情入口。

## 权限

- 指标读取需要 `metric.read`。
- 故障读取需要 `fault.read`，故障写入需要新增的 `fault.write`。
- 候选站点读取需要 `candidate.read`，创建/编辑/删除/状态变更需要 `candidate.write`。
- 写入操作同时经过用户数据集和区域范围校验。

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/metrics` | 运营指标分页查询 |
| `GET` | `/stations/{station_id}/metrics` | 站点运营指标 |
| `GET` | `/faults` | 故障事件分页查询 |
| `GET` | `/stations/{station_id}/faults` | 站点故障事件 |
| `POST` | `/stations/{station_id}/faults` | 创建故障 |
| `PATCH` | `/faults/{fault_id}` | 更新恢复时间和严重等级 |
| `GET` | `/candidate-sites` | 候选站点列表 |
| `POST` | `/candidate-sites` | 创建候选站点 |
| `GET` | `/candidate-sites/{candidate_id}` | 候选站点详情 |
| `PATCH` | `/candidate-sites/{candidate_id}` | 编辑候选站点 |
| `POST` | `/candidate-sites/{candidate_id}/status` | 修改候选站点状态 |
| `DELETE` | `/candidate-sites/{candidate_id}` | 软删除候选站点 |

## 验证记录

现有数据库包含 504 条运营指标、31 条故障和 12 个候选站点。验证结果：

- 运营指标查询 HTTP 200，返回 5 条分页数据。
- 故障列表 HTTP 200；故障创建 HTTP 201；恢复时间和状态更新 HTTP 200。
- 不完整候选点创建 HTTP 201，但请求进入 `RECOMMENDED` 被拒绝并返回 422 `CANDIDATE_NOT_EVALUABLE`。
- 补齐关键字段后候选点更新 HTTP 200，`evaluable=true`、`recommendable=true`。
- 候选点软删除 HTTP 204。
- 测试数据已清理，原有统计恢复为 504/31/12。

## 产物

- `backend/app/schemas/operations.py`
- `backend/app/services/operations.py`
- `backend/app/api/routes/operations.py`
- `backend/app/authorization.py`

