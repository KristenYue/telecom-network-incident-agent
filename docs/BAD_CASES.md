# Bad Cases 与工程闭环

## BC-001：Redis `BLPOP` 取出后进程崩溃导致任务丢失

- 复现：Worker 从 List 弹出任务，在 `process_job` 完成前终止进程。
- 根因：`BLPOP` 同时完成“领取”和“删除”，没有确认阶段，也没有处理中状态。
- 修复：迁移到 Redis Streams consumer group；成功后显式 `XACK`，失败保持 pending，超时使用 `XAUTOCLAIM` 接管，超限写入 dead-letter Stream。
- 回归：队列状态机单元测试、Worker settle 测试、真实 Redis reclaim/DLQ CI。

## BC-002：同一错误无限重试阻塞队列

- 复现：确定性坏输入或持续工具错误每次接管后继续失败。
- 根因：只有重投，没有投递上限与隔离通道。
- 修复：按 consumer-group delivery count 限制处理次数；超过阈值后保存原载荷、最后错误和投递次数到死信 Stream。

## BC-003：Worker 失租后仍可能写入成功结果

- 复现：Worker A 长调用期间 lease 过期，Worker B 接管，随后 A 返回并尝试保存。
- 根因：仅有超时租约，写入没有执行代际约束。
- 修复：单调 fencing token 进入 checkpoint/tool-result 写入条件；旧 token 抛 `StaleLeaseWriteError`。
- 回归：真实 PostgreSQL 双 Worker takeover 测试。

## BC-004：未注册危险工具异常类型与安全评测预期不一致

- 现象：安全 cohort 预期底层 `KeyError`，Runtime 对外实际返回 `ValueError`。
- 根因：测试依赖实现细节而不是公共契约。
- 修复：按 Runtime 对外异常语义验证，并断言工具执行数为 0。

## BC-005：冻结评测分母为空却显示 0%

- 现象：候选冻结集没有注入样本，旧计算用 `max(1, count)` 得到 0%。
- 根因：用数学兜底掩盖数据覆盖缺失。
- 修复：封存前强制检查 cohort 分母；无样本时指标为 `null`，重新生成含 12 条注入输入的冻结集。

## BC-006：Windows TestClient 生命周期无法退出

- 现象：HTTP 生命周期测试完成断言后挂起。
- 处理：Windows 保留路由/服务契约测试，真实 HTTP、Compose 和健康检查交由 Linux CI 执行；不把宿主限制记录为业务通过或失败。
