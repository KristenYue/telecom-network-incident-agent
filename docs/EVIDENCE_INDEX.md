# 三方向研发证据索引

以实际结果选择阅读入口：逻辑仿真、原生模型执行、ROS2和真实硬件不混用。

| 方向/能力 | 已运行证据 | 核心源码 | 可复现入口 |
|---|---|---|---|
| 机器人真实模型规划 | [3轮决策、2次工具](evidence/robot-live.json) | [任务与Planner](../src/telecom_incident_agent/robot_tasks.py) | `scripts/demo_robot_agent.py` |
| 机器人进度与取消 | [取消记录](evidence/robot-cancel.json) | [技能契约](../src/telecom_incident_agent/robot_skills.py) | `demo_robot_agent.py --baseline --cancel-after 1` |
| API与SSE | [契约验证源码](../tests/test_robot_api_contract.py) | [API](../src/telecom_incident_agent/robot_api.py) | `pytest tests/test_robot_api_contract.py` |
| 真实模型+C++设备+原生推理 | [联合轨迹](evidence/native-llm-live.json) | [知识工具](../src/telecom_incident_agent/industrial_diagnosis.py) | `scripts/demo_native_llm.py` |
| 原生Embedding知识检索 | [实际查询](evidence/native-retrieval.json) | [知识索引](../src/telecom_incident_agent/knowledge.py) | `scripts/demo_native_retrieval.py` |
| 车辆真实模型、审批与执行 | [完整轨迹](evidence/vehicle-live.json) | [模型Planner](../src/telecom_incident_agent/vehicle_llm.py) | `demo_vehicle.py --live-model` |
| 车辆遥测与幂等控制 | [规则业务记录](evidence/vehicle-baseline.json) | [车辆服务](../src/telecom_incident_agent/vehicle.py) | `scripts/demo_vehicle.py` |
| DBC解码 | [帧解码和拒绝结果](evidence/vehicle-dbc.json) | [子集解析器](../src/telecom_incident_agent/vehicle_signals.py) | `scripts/verify_vehicle_dbc.py` |

跨仓库：[原生SDK与Windows实测](https://github.com/KristenYue/edge-device-verification-lab/tree/main/inference_sdk)、[共享Runtime](https://github.com/KristenYue/agent-runtime-quality-platform)。对应新增文件需发布后远程链接才生效。

## 面试要能解释的设计

- Robot：LLM提出动作，注册表和参数契约决定能否执行；反馈进入下一轮上下文，重试有明确条件和次数。
- Runtime：审批、执行权、Checkpoint与幂等账本是独立责任；机器人本地任务Worker不是新的分布式框架。
- SDK：输入对象生命周期、GIL边界和输出所有权；原生封装不自动意味着更快，实际BGE对照没有性能提升。
- Vehicle：确认是服务端状态迁移；同一事务提交仿真命令与状态；补传时间不改变采样数据年龄。
- 范围：机器人是逻辑工作站；车辆是合成信号与服务；SDK是CPU EP；不宣称真机、量产或芯片硬件适配。

## 待验收

新增ROS2传输的Linux执行、Ubuntu SDK构建、vcan收发和HTTP服务器级联调。已有旧ROS2 CI记录不能替代新Adapter运行。模型调用密钥只在环境变量中读取，不随结果导出。
