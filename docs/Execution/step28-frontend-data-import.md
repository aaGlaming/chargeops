# Step 28：实现前端业务数据导入

## 实现内容

- 新增“数据导入”菜单和 `/imports` 路由，只有具备 `menu.imports` 的运营/政策/系统角色可见。
- 新增站点、连接器、运营指标、故障事件、候选站点和扩容案例六类数据集选择器。
- 新增六类 CSV 模板下载；同时补齐 `stations_template.csv` 和 `connectors_template.csv`。
- 上传区支持 CSV、JSON 和 GeoJSON（FeatureCollection）文件，浏览器内完成预览，同时提供 `/imports/preview` 后端校验契约，不渲染不可信 HTML。
- 自动按字段名匹配目标字段，支持手动调整映射，并展示目标字段类型、是否必填和示例提示。
- 在导入确认前执行必填项、数字、坐标、日期、利用率范围校验，展示行号、字段、级别、原因和修复建议。
- 支持失败记录 CSV 下载、导入进度、成功/失败/提示统计和批次登记结果。
- 新增 `/imports` FastAPI 接口，确认后写入 `import_batch`、对应业务表和 `import_row_error`，支持批次列表、详情、失败记录下载和回滚。
- 增加批次列表、批次详情抽屉、数据版本、文件名、成功数和失败数展示，并提供回滚确认入口。
- 导入完成后发出 `chargeops:data-imported` 和 `chargeops:data-refresh-requested` 事件，供站点列表、地图、Agent 和驾驶舱页面刷新数据。
- 所有空数据、解析失败、权限不足和导入中的状态均有独立界面承载。

## 主要文件

- `frontend/src/views/ImportView.vue`
- `frontend/src/api/imports.ts`
- `backend/app/api/routes/imports.py`
- `backend/app/services/imports.py`
- `backend/app/schemas/imports.py`
- `frontend/src/router/index.ts`
- `frontend/src/layouts/AppShell.vue`
- `frontend/src/styles/main.css`
- `data/templates/stations_template.csv`
- `data/templates/connectors_template.csv`

## 验证

在 `frontend` 目录执行：

```powershell
npm run build
```

结果：`vue-tsc --noEmit`、`vite build` 和 `python -m compileall -q backend/app` 均通过。Vite 仍提示主入口 chunk 较大，后续业务页面接入接口时继续按路由拆分即可。

