# 三分钟演示脚本

1. 展示 README 的事实边界：全部合成，不连接真实设备。
2. 运行 `python -m telecom_incident_agent.demo`。
3. 指出第一阶段并发读取设备、接口、BGP/OSPF、路径、指标和关联告警。
4. 展示根因的每条 evidence ID 与合成手册引用。
5. 展示 `replace_optic` 触发 Runtime `waiting_review`。
6. 人工批准后强调 `execution_performed=false`：系统只创建审批记录与工单草稿。
7. 打开冻结评测报告，说明 60 条是合成契约任务，100% 不是生产准确率。
