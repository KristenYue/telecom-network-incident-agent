# 工具契约与权限

| 工具 | 等级 | Runtime 权限 | 副作用 |
|---|---:|---|---|
| `search_runbook` | L0 | read | 无 |
| `get_device_status` | L1 | read | 无 |
| `get_interface_status` | L1 | read | 无 |
| `get_routing_neighbors` | L1 | read | 无 |
| `query_metrics` | L1 | read | 无 |
| `list_related_alarms` | L1 | read | 无 |
| `run_path_probe` | L2 | compute | 仅合成探测 |
| `create_ticket_draft` | L3 | write + replay-safe | 仅本地草稿 |
| `request_change_approval` | L4 gate | dangerous + replay-safe | 仅审批记录；不执行变更 |

每个工具具有 Pydantic 参数校验、确定性响应、类型化错误、Runtime Trace、幂等键和失败注入。Runtime 限制最多 10 次工具调用和 8 个步骤。设备 ID 与接口名使用白名单正则；Planner 无法覆盖 Runtime 注入的幂等上下文。

真实接口重启、路由修改、设备重启和进程终止工具不存在于注册表中，因此即使批准也无法由本项目执行。
