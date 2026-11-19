# 机器人技能与任务执行：阶段交付

## 已运行

2026-11-19真实LLM新链路验收通过：[模型轨迹](evidence/robot-live.json)。模型3次决策，调用get_robot_status和inspect_workcell两个工具，Runtime完成巡检并持久化报告。执行器为逻辑工作站，非ROS2或物理机器人，本记录不替代ROS2实跑。

2026-11-19 Windows本机执行规则Planner驱动的逻辑工作站：三点巡检完成、进度触发取消、设备离线失败关闭。原始结果分别在 `evidence/robot-baseline.json`、`robot-cancel.json`、`robot-offline.json`。这些不是实际LLM或ROS2本次运行证据。

核心源码：`robot_skills.py` 定义参数与传输接口，`robot_tasks.py` 复用共享AgentRuntime，提供SQLite任务、幂等提交和单后台Worker；`robot_api.py` 提供REST与可续读SSE。

## 运行

```bash
pip install -e '.[dev]'
python scripts/demo_robot_agent.py --baseline --output docs/evidence/robot-baseline.json
python -m pytest tests/test_robot_tasks.py -q
robot-agent-api
```

真实模型：本机安全配置 `TELECOM_MODEL_BASE_URL`、`TELECOM_MODEL_ID`、`TELECOM_MODEL_API_KEY`，去掉 `--baseline`，将结果另存为 `robot-live.json`。不能覆盖规则证据冒充模型结果。

## 工程日志与Bad Case

- 同一幂等键并发提交只能产生一个任务；不同载荷返回冲突。
- 取消是请求，终态以执行器返回为准；完成与取消竞争不能把已完成动作伪装成撤销。
- 重启遇到未完成本地任务标记result_unknown，禁止盲目重放非幂等技能。
- SSE从数据库按游标读取，每批最多100条，无订阅者独立内存队列；当前事件库不自动清理，长期部署需要归档策略。
- Windows使用已有同步SQLite兼容Runtime，不能作为Linux心跳或分布式接管证明。
- 回归发现此前知识库文档身份遗漏设备系列，以及无告警网络诊断出现默认根因，已修正并重新验证。

## 待完成

真实模型多步骤与有限重规划验收；ROS2新传输的Linux实际运行；HTTP服务器端到端联调。当前没有Gazebo/Nav2物理导航。

## 第二阶段日志

`robot_ros.py` 已实现状态Service与巡检Action适配：将反馈写入任务事件，传播取消请求，以ROS GoalStatus判定终态；提交或结果超时标记未知，不盲目重试。通过 `demo_robot_agent.py --ros2` 显式选择，无逻辑仿真回退。

API端点契约及已完成任务SSE重放检查通过；与重复提交、取消及离线共4项针对性检查通过。该检查直接调用端点，不冒充真实HTTP服务器压测。已添加ROS2 CI执行命令，但尚未推送或运行。

Linux路径将同步模型和设备调用放入线程，防止阻塞共享Runtime心跳；Windows兼容执行路径单独保留。长期阻塞模型请求仍受HTTP超时约束，取消模型调用不代表底层请求立刻中断。

收尾检查：保留result_unknown终态，不把ROS结果超时等同已失败。新增Planner边界检查证明只对显式retry_safe失败允许有限重试；模型测试替身仅验证约束，不作为真实LLM证据。整库回归通过，环境相关跳过项不计成功运行。
