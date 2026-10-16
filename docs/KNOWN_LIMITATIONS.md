# 已知限制

- 当前根因排序是透明规则基线，不是训练出的通信大模型。
- 只有 12 份小型合成手册，没有厂商私有命令和真实版本矩阵。
- 当前 API 审计索引与 Runtime checkpoint 使用 SQLite。
- PostgreSQL/Redis Worker、lease 接管集成、Prometheus/Grafana 和独立 Trace 页面尚未完成本项目验收。
- Dockerfile/Compose 已提供 C1 API 启动路径，但本机没有 Docker，尚无本机镜像构建证据。
- 失败注入验证工具、策略和幂等语义，不代表覆盖所有真实设备或供应商异常。
- 所有延迟均为本地合成执行耗时，不是生产 SLA。
- Windows 沙箱兼容层不验证异步并发、heartbeat 或跨 Worker 接管。
