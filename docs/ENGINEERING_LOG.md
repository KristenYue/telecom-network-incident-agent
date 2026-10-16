# 工程日志

## 2026-10-16：C0–C1 与 C2/C3 主体

1. 冻结 12 类 IP 网络/传输链路故障，明确安全动作、审批动作和信息不足问题。
2. 实现 9 个合成工具、严格输入契约、故障注入、权限和幂等写入。
3. 接入共享 Runtime，而非复制 Planner loop、checkpoint、lease、fencing 和 Trace。
4. 实现证据优先排序、合成 runbook 检索、工单草稿和人工审批恢复。
5. 生成 60 条版本化合成任务与 SHA-256 manifest。
6. 首次评测发现接口 Down 和告警风暴会被下游丢包症状错误排到后面；修复为按因果证据强度提升根因。
7. 冻结套件最终通过 Top-1、Top-3、证据、审批与注入门禁。

### 环境问题

托管 Windows 沙箱中，最小 `asyncio.run()`、`asyncio.sleep(0)` 和 `asyncio.to_thread()` 无法退出。该问题独立于通信代码。为可复现离线验证，Windows 合成路径使用：

- 直接 SQLite async protocol adapter；
- 顺序执行本地 fixture；
- 不启动 heartbeat 的亚秒级租约；
- 只允许不让出控制权的离线协程驱动器。

Linux/CI 仍使用共享 Runtime 原生异步批次和 heartbeat。Windows 兼容结果不用于声称生产并发或恢复能力。

## 2026-10-16：C4 服务化交付

1. 增加 PostgreSQL incident repository，并把 Runtime checkpoint、lease、fencing 切换到共享 Runtime 的 `PostgresRuntimeBackend`。
2. 增加 Redis 队列；API 只负责受理和审计，独立 Worker 执行诊断或审批恢复。
3. 增加 `/ready`、`/metrics` 和无框架 `/trace-ui`，Trace 页面只渲染经过转义的 API 数据。
4. 增加 Prometheus 抓取配置和 Grafana dashboard provisioning。
5. 将 Compose 扩展为 API、Worker、PostgreSQL、Redis、Prometheus、Grafana 六服务，并添加健康检查。
6. 新增部署契约测试和 Linux CI Compose smoke test。本机没有 Docker，不把静态检查声明为本机启动成功。
