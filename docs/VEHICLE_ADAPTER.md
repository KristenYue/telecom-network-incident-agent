# 智能车辆服务适配与Agent执行

车辆领域扩展复用共享Agent Runtime。当前执行器为SQLite中的车辆仿真服务，没有真实CAN、vcan、ECU或量产车辆。

```mermaid
flowchart LR
 A[任务请求] --> B[Planner]
 B --> R[共享Runtime]
 R --> Q[胎压 / 状态只读工具]
 R --> H[人工确认]
 H --> C[模拟空调服务]
 Q --> S[车辆遥测与新鲜度]
 C --> L[原子命令账本]
```

## 已运行的业务链

真实LLM验收已执行：[模型轨迹](evidence/vehicle-live.json)。胎压诊断与模拟空调控制经模型规划，控制请求进入waiting_review后由演示程序显式批准，最终completed。审批为演示授权步骤，不宣称真实用户审批系统或真实车辆。

1. 读取合成胎压，返回低压轮胎、原始快照和项目阈值。220kPa仅为演示阈值，非车型标准。
2. 空调22℃请求先进入Runtime `waiting_review`；显式批准后执行并完成，命令与状态在同一事务提交。
3. 离线遥测先进入有界待传记录，恢复时模拟补传；按采样时间选择最新状态，延迟旧数据不覆盖新状态。

[原始运行证据](evidence/vehicle-baseline.json)明确标记规则Planner，不冒充真实模型。

```bash
python scripts/demo_vehicle.py --output docs/evidence/vehicle-baseline.json
python -m pytest tests/test_vehicle.py -q
```

## 核心模块与Bad Case

`src/telecom_incident_agent/vehicle.py`负责服务和工具注册；不复制Runtime。命令账本覆盖同一SQLite事务内的仿真副作用，不宣称任意远端设备exactly-once。

- 幂等键换参数：拒绝，防止同一命令身份执行不同温度。
- 离线缓冲达到容量：拒绝新样本，显式报告溢出。
- 过期遥测：返回unknown，不能依据旧胎压报告当前安全状态。
- 补传晚到：保存历史但不替换更新的采样状态。

`examples/vehicle.dbc`提供项目自建报文规范；`vehicle_signals.py`已执行该规范的unsigned little-endian经典CAN子集解码，拒绝不支持的信号格式，不是通用DBC解析器。

实际验证：[DBC记录](evidence/vehicle-dbc.json)，两帧分别解出12.34km/h、62%电量、车门状态及190kPa左前轮胎压；未知ID、错误DLC、超范围车速均拒绝。

新增五类项目自建车辆知识与版本化引用：胎压、电量、车门、空调和数据新鲜度。规则演示已执行胎压观测→知识查询→报告证据；这属于受控知识查找，不宣称大型语义RAG。

`vehicle_llm.py`已提供真实模型规划入口，通过 `demo_vehicle.py --live-model`运行。车型工具白名单、温度范围和服务端写许可独立校验，批准由共享Runtime处理。当前尚未取得该新链路的实际LLM运行结果。

SocketCAN/vcan实跑及真实LLM验收仍待完成。当前仿真补传不是实际MQTT链路；真实MQTT/TLS证据仍属于独立IoT项目。
