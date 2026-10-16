# 已知限制

- 当前根因排序是透明规则基线，不是训练出的通信大模型。
- 只有 12 份小型合成手册，没有厂商私有命令和真实版本矩阵。
- 本机离线模式使用 SQLite；Compose 模式使用 PostgreSQL 审计索引和 Runtime checkpoint/lease backend。
- PostgreSQL/Redis Worker、Prometheus/Grafana 和 Trace 页面已经实现并有契约测试，但本机没有 Docker，尚无本机镜像与服务启动证据。
- 浏览器 Trace 页面是只读调试界面，不是完整 NOC 工单前端。
- 失败注入验证工具、策略和幂等语义，不代表覆盖所有真实设备或供应商异常。
- 所有延迟均为本地合成执行耗时，不是生产 SLA。
- Windows 沙箱兼容层不验证异步并发、heartbeat 或跨 Worker 接管。
