# 机器人技能接入与任务执行

[项目总览](../README.md) · [真实模型记录](evidence/robot-live.json) · [ROS 2 验收](https://github.com/KristenYue/telecom-network-incident-agent/actions/runs/44509829892)

## 业务闭环与职责

自然语言目标 → Planner 选择已注册工具 → 读取工作站状态 → 提交巡检 Action → 进度事件 → 完成 / 取消 → 报告与 Trace。`robot_tasks.py` 管理本地任务、幂等提交和事件；共享 Runtime 管理规划 / 执行；`robot_ros.py` 只负责传输。

| 模块 | 源码 | 职责 |
|---|---|---|
| 技能契约 | [robot_skills.py](../src/telecom_incident_agent/robot_skills.py) | 参数、前置状态、Transport Protocol、逻辑工作站 |
| Planner 与任务 | [robot_tasks.py](../src/telecom_incident_agent/robot_tasks.py) | SQLite 本地任务、单 Worker、观测约束、有限重试 |
| API 与事件流 | [robot_api.py](../src/telecom_incident_agent/robot_api.py) | 提交 / 查询 / 取消，SSE 游标续读 |
| ROS Adapter | [robot_ros.py](../src/telecom_incident_agent/robot_ros.py) | Context / Executor、Service、Action、反馈与取消 |
| 仿真工作站 | [industrial_robot_sim](../ros2/industrial_robot_sim) | Topic 状态、Trigger Service、Inspect Action |

## 已验收结果

- **真实模型 + 逻辑工作站**：[3 次决策 / 2 次工具调用](evidence/robot-live.json)，完成三点巡检。
- **规则 Planner + Linux ROS 2 + Runtime**：[3/3 点完成](evidence/cloud-ros2/robot-completed.json)，[1/3 点取消](evidence/cloud-ros2/robot-canceled.json)。进度与终态保存在任务事件中。
- **ROS 基础接口**：[Topic](evidence/cloud-ros2/topic.txt)、[Service](evidence/cloud-ros2/service.txt)、[Action 类型](evidence/cloud-ros2/actions.txt)、[8 点巡检](evidence/cloud-ros2/completed.json)与[中途取消](evidence/cloud-ros2/canceled.json)通过。
- 同轮 `test-and-gate`、`redis-reliability`、`postgres-takeover`、`compose-smoke` 全部通过；后四项属于业务部署或集成路径，不等同机器人本地单 Worker 变为分布式。

真实模型和 ROS 2 分别验收，不合并声称联合真实模型驱动 ROS 2 已运行。

## 本地演示

```bash
python -m pip install -e '.[dev]'
python scripts/demo_robot_agent.py --baseline --output .runtime/robot.json
python scripts/demo_robot_agent.py --baseline --cancel-after 1 --output .runtime/robot-cancel.json
robot-agent-api
```

真实模型配置三项 `TELECOM_MODEL_*` 环境变量，移除 `--baseline`。结果另存，不覆盖规则证据。

## Linux ROS 2 Jazzy

先安装 ROS 2 Jazzy 与 colcon，并激活已安装本项目的 Python 环境。

```bash
source /opt/ros/jazzy/setup.bash
colcon build --base-paths ros2
source install/setup.bash
export ROS_LOCALHOST_ONLY=1
python3 -u ros2/industrial_robot_sim/scripts/workcell_sim
```

第二个终端进入同一仓库并 source 上述两个 setup 文件，再执行：

```bash
python scripts/demo_robot_agent.py --ros2 --baseline --data-dir .runtime/ros-complete --output .runtime/ros-completed.json
python scripts/demo_robot_agent.py --ros2 --baseline --cancel-after 1 --data-dir .runtime/ros-cancel --output .runtime/ros-canceled.json
```

[托管环境完整命令](../.github/workflows/ci.yml)。Topic `/workcell/status`，Service `/workcell/get_status`，Action `/workcell/inspect`。

## 设计取舍与 Bad Case

1. 同幂等键同载荷返回原任务，换载荷拒绝；事件写入 SQLite 后按 ID 查询。
2. 取消是请求，最终依据执行器；不能把已经发生的动作视为撤销。
3. 未完成本地任务重启后标记 `result_unknown`，不盲目重放非幂等技能。
4. 只对显式 `retry_safe` 失败做有限重试；结果未知时终止。
5. Linux 同步模型 / 工具通过线程执行，避免阻塞 Runtime 心跳；Windows 同步兼容路径单独说明。
6. ROS 发现有启动延迟，须先等待服务、明确 Topic 类型并保留日志；自定义 Context 须绑定同一 Executor，避免全局默认 Context 错配。
7. SSE 每批最多 100 条、无客户端独立内存队列；当前端点契约已验证，长期事件归档与 HTTP 服务器级性能尚未作为成果。

这是 ROS 2 逻辑工作站，未包含 Gazebo / Nav2、物理导航或真机运动控制。
