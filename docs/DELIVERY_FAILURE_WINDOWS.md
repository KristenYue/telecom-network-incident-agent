# 跨存储交付失败窗口

结果已提交、Redis 尚未收到 XACK 时，Worker 崩溃可能导致 Stream 消息重投。消费端读取业务记录，发现已持久化终态即可返回已有结果并确认消息。重复诊断消息遇到已保存的等待审批状态时也可以确认。定向测试用已提交的仓储替身验证重投只确认消息。

## V2.0 PostgreSQL Outbox 与设备演示

基准提交 `4f8a1c8`。配置 PostgreSQL 和 Redis 时，API 在同一个 SQL 事务里写入事件和诊断任务；审批恢复同样将符合条件的状态流转与事件写入绑定。Worker 按事件 ID 分批扫描，Redis 发布成功后删除记录。SQLite 本地模式沿用原入口。

Bad Case：Worker 在 Redis 写入之后、删除数据库记录之前中断，重启会发布相同的事件 ID。回归测试复现了两份相同载荷。另一条回归覆盖结果已写入但 Redis 尚未 ACK 的串行重投。多个 Worker 并发发布可能产生重复消息，现有运行时 checkpoint fencing 与 incident 投影写入是不同边界。仍需真实服务复现接管竞争，并把投影更新与执行权检查合入一个事务。

## 复现设备执行

在父工作区打开两个 PowerShell。第一处从新设备进程启动，第二处复用项目一的 Python 协议客户端。演示只连接本机模拟设备。

```powershell
Set-Location edge-device-verification-lab
.\scripts\build_windows.cmd
.\build\edge_device_simulator.exe --port 18765 --log build/device-demo-events.jsonl
```

```powershell
$env:PYTHONPATH = (Resolve-Path 'edge-device-verification-lab/src').Path
$py = '.\telecom-network-incident-agent\.venv\Scripts\python.exe'
& $py telecom-network-incident-agent/scripts/demo_device_task.py run --allow-sim-write --port 18765
& $py telecom-network-incident-agent/scripts/demo_device_task.py interlock --allow-sim-write --port 18765
```

正常轨迹从 BOOT 经归位、校准、加载配置到 COMPLETE，设备返回 R-1、最终 run_count=1。联锁轨迹先进入 E_STOP，再由设备拒绝 start_run。两份轨迹分别见 [任务完成](device-demo-run.jsonl) 和 [联锁拒绝](device-demo-interlock.jsonl)。停止设备后执行同一个脚本的 `status` 场景，可看到 [传输失败及对账失败](device-demo-status.jsonl)，返回码为 3。

CLI 和 API 共用确定性编排。task ID 派生每步请求 ID，传输异常后只读查询并停止。

## FastAPI 持久化设备任务

设备任务采用 SQL 队列，复用 SQLite / PostgreSQL 连接。网络诊断任务继续走 Redis Streams。API 提交后立即返回任务 ID，Worker 原子领取，执行结果和轨迹经同一条带持有者检查的更新落库。每个模拟器一次只领取一个任务。Worker 中断导致执行权过期时，任务进入 `outcome_unknown`，迟到结果无法覆盖该状态。外部设备可能已经收到指令，因此过期任务不自动重放。

保持模拟器运行，在父工作区另开 PowerShell：

```powershell
$env:PYTHONPATH = (Resolve-Path 'edge-device-verification-lab/src').Path
$env:TELECOM_SIMULATOR_PORT = '18765'
$env:TELECOM_SIMULATOR_ALLOW_WRITES = '1'
Set-Location telecom-network-incident-agent
.\.venv\Scripts\python.exe -m uvicorn telecom_incident_agent.api:app --host 127.0.0.1 --port 18000
```

在第三个窗口进入任务平台目录，执行 `.\.venv\Scripts\python.exe scripts/smoke_device_api.py`。停止模拟器后加 `--offline`。无服务器与请求双重授权时，写任务返回 403。部署独立 Worker 时需要让其 Python 环境能导入项目一的 `edge_validation`，并让模拟器监听同一网络命名空间中的回环端口。

Windows 已用真实 HTTP、SQLite Worker 和 C++ TCP 进程跑通三个场景，输出见 [API 运行轨迹](device-api-smoke.jsonl)。测试还覆盖 API 重启后领取既有任务、租约过期与旧 Worker 回写拒绝。PostgreSQL 环境已加专门的集成用例，运行状态以真实服务执行结果为准。
