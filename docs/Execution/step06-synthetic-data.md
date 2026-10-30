# Step 6：准备用户上传模板和合成业务数据

## 执行结果

- 生成器：`scripts/generate_synthetic_data.py`
- 生成器版本：`chargeops-synthetic-v1.0.0`
- 固定随机种子：`20261029`
- 生成时间：`2026-10-29T12:00:00-07:00`
- 合成批次 ID：`synthetic-demo-2026-10-29-v1`
- 区域：加州（`CA`）
- 所有合成记录都包含 `source_type=synthetic`、生成器版本、生成时间和批次 ID。

## 上传模板

模板写入 `data/templates`：

- `candidate_sites_template.csv`
- `station_metrics_template.csv`
- `station_faults_template.csv`
- `expansion_cases_template.csv`
- `policy_matching_cases_template.csv`（为政策匹配演示补充）

模板包含业务字段、数据时效字段和合成数据追溯字段，可供后续 Step 8/9 的字段映射和导入校验使用。

## 合成数据

数据写入 `data/raw/synthetic`：

| 文件 | 行数 | 主要用途 |
|---|---:|---|
| `candidate_sites_synthetic_2026-10-29.csv` | 12 | 候选地址、面积、停车位、电力容量、预算和交通指标 |
| `station_metrics_synthetic_2026-10-29.csv` | 504 | 12 个站点、14 天、每日 3 个时段的运营指标 |
| `station_faults_synthetic_2026-10-29.csv` | 31 | 故障类型、严重等级、恢复时间和影响连接器 |
| `expansion_cases_synthetic_2026-10-29.csv` | 8 | 扩容预算、连接器数量、优先级和前置条件 |
| `policy_matching_cases_synthetic_2026-10-29.csv` | 4 | 政策版本、资格判断、缺少材料和申请截止日期 |

## 场景覆盖

已包含以下验收场景：

- 正常数据
- 高利用率站点
- 低利用率站点
- 故障集中站点（`SYN-ST-007`）
- 缺失坐标候选点
- 缺失电力容量扩容案例
- 过期运营/故障/扩容/政策数据
- 政策候选和部分匹配案例

合成数据明确标记为演示数据，不能当作真实运营数据、订单数据或政策结论使用。

## 清单和校验

- 清单：`data/manifests/synthetic_demo_2026-10-29.json`
- SHA-256 清单：`data/manifests/synthetic_demo_2026-10-29.sha256`
- 使用固定种子重新执行生成器后，文件内容和 SHA-256 保持一致。
- 本步骤只准备模板和原始合成文件，不提前写入最终业务表；批次导入、字段校验和失败行处理在 Step 9 执行。
