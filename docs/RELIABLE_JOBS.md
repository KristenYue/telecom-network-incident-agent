# Redis Streams 可靠任务设计

## 目标

API 返回 `queued` 后，诊断任务必须在 Worker 崩溃、进程重启和临时工具失败条件下保持可恢复，不能因为消费者已经取走消息而静默丢失。

## 状态流转

```text
XADD stream
  -> XREADGROUP 首次投递
  -> pending-entry list
       -> 业务完成: XACK + XDEL
       -> 处理异常: 保持 pending + 记录 last_error
       -> Worker 消失: XAUTOCLAIM 转移给其他 consumer
       -> deliveries 超限: XADD dead-letter + XACK + XDEL
```

Stream、consumer group 和死信队列使用版本化 key：

- `telecom:incident-jobs:v2`
- `telecom-runtime-workers:v2`
- `telecom:incident-jobs:v2:dead-letter`

## 一致性边界

消息确认发生在 `IncidentService.process_job` 返回之后，因此 Runtime checkpoint、工具结果账本和最终 incident 记录已经落库。若 Worker 在落库后、确认前退出，消息会被再次投递；重复执行由固定 `incident_id`、Runtime 幂等键、PostgreSQL upsert 和 fencing token 共同约束。

这是一条 at-least-once 任务链：允许可识别的重投，不依赖“消息永远只出现一次”的假设。外部写工具仍必须接受幂等键；无法确认副作用状态的操作由 Runtime 失败关闭。

## 故障策略

| 故障 | 行为 | 证据 |
|---|---|---|
| Worker 取消息后崩溃 | 消息保留在 pending，超时后由其他 consumer reclaim | 真实 Redis CI 集成测试 |
| 工具/业务异常 | 记录最后错误，不确认消息 | Worker 单元测试 |
| 连续投递超限 | 写入 dead-letter Stream，随后确认原消息 | 单元测试 + Redis 集成测试 |
| 旧 Worker 恢复并写状态 | PostgreSQL fencing token 拒绝旧代际 | PostgreSQL takeover CI |
| 非法 JSON/非对象载荷 | 直接进入 dead-letter，避免阻塞消费组 | 队列契约测试 |

## 可配置项

- `TELECOM_JOB_VISIBILITY_TIMEOUT_SECONDS`：默认 30 秒。
- `TELECOM_JOB_MAX_DELIVERIES`：默认 3 次实际处理机会。

生产部署应结合诊断耗时设置 visibility timeout，并对死信 Stream 长度和最老消息年龄配置告警。
