# API 契约

## 创建诊断任务

`POST /v1/incidents`

请求体使用 `IncidentRequest`：`case_id`、`topology_summary`、`alarms`、`logs`、`metrics`、`allowed_runbooks`、`requested_actions` 和仅用于合成测试的 `failure_injections`。

本地 SQLite 模式直接返回 Runtime 结果。Compose 模式先返回 `queued`，独立 Worker 完成后变为 `completed` 或 `waiting_review`；客户端通过查询接口获取结果。

## 查询与 Trace

- `GET /v1/incidents/{incident_id}`：任务与最新结果。
- `GET /v1/incidents/{incident_id}/trace`：步骤、工具调用、错误、待审批动作和领域结果。
- `GET /trace-ui`：只读浏览器 Trace 查看器。
- `GET /ready`：PostgreSQL/Redis 依赖就绪检查。
- `GET /metrics`：Prometheus 指标。

## 人工审批

先调用 `POST /v1/incidents/{incident_id}/reviews`：

```json
{"approved": true, "reviewer": "operator-01", "message": "只批准生成变更草稿"}
```

再调用 `POST /v1/incidents/{incident_id}/resume`。Compose 模式会返回 `queued_resume` 并由 Worker 恢复；拒绝最终进入 `failed_closed`，批准只创建审批记录和工单草稿。

## 手册检索

`GET /v1/runbooks/search?query=bgp&fault_type=bgp_neighbor_down`

返回合成手册证据。检索文本永远按不可信数据处理，不能成为系统指令。
