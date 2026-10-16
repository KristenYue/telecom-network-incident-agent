"""Small, explicitly synthetic runbook corpus used by the offline demo."""

from __future__ import annotations

from typing import Any


RUNBOOKS: tuple[dict[str, Any], ...] = (
    {"runbook_id": "rb-interface-001", "fault_type": "interface_down", "device_family": "generic-router", "version": "2026.1", "title": "接口 Down 只读排查", "steps": ["核对管理状态与运行状态", "检查最近状态变化与对端告警", "核对物理连接；任何端口重启必须审批"], "keywords": ["link_down", "接口", "down"]},
    {"runbook_id": "rb-optical-001", "fault_type": "optical_power_abnormal", "device_family": "generic-optical", "version": "2026.1", "title": "光功率异常排查", "steps": ["读取收发光功率", "核对模块阈值和链路预算", "清洁连接器；更换模块必须审批"], "keywords": ["rx_power", "光功率", "optic"]},
    {"runbook_id": "rb-ber-001", "fault_type": "high_ber", "device_family": "generic-optical", "version": "2026.1", "title": "高误码率排查", "steps": ["对齐 BER 与 CRC 时间窗口", "核对光功率和线路告警", "保留替换链路前后的指标证据"], "keywords": ["ber", "crc", "误码"]},
    {"runbook_id": "rb-loss-001", "fault_type": "packet_loss", "device_family": "generic-router", "version": "2026.1", "title": "丢包分段定位", "steps": ["检查接口丢弃和错误计数", "执行受预算限制的路径探测", "核对拥塞与物理错误"], "keywords": ["packet_loss", "丢包", "drop"]},
    {"runbook_id": "rb-latency-001", "fault_type": "latency_jitter", "device_family": "generic-router", "version": "2026.1", "title": "时延与抖动排查", "steps": ["比较当前值和冻结基线", "执行逐跳探测", "定位首个异常跳点"], "keywords": ["latency", "jitter", "时延"]},
    {"runbook_id": "rb-util-001", "fault_type": "high_utilization", "device_family": "generic-router", "version": "2026.1", "title": "带宽高利用率排查", "steps": ["确认峰值与持续时间", "区分业务增长和异常流量", "QoS 或限速变更必须审批"], "keywords": ["utilization", "bandwidth", "利用率"]},
    {"runbook_id": "rb-bgp-001", "fault_type": "bgp_neighbor_down", "device_family": "generic-router", "version": "2026.1", "title": "BGP 邻居中断排查", "steps": ["检查邻居状态和最后变化原因", "检查对端可达性", "清会话或改路由策略必须审批"], "keywords": ["bgp", "neighbor", "邻居"]},
    {"runbook_id": "rb-ospf-001", "fault_type": "ospf_adjacency", "device_family": "generic-router", "version": "2026.1", "title": "OSPF 邻接排查", "steps": ["核对区域、MTU 与 Hello 参数", "检查状态卡在哪一阶段", "重置进程必须审批"], "keywords": ["ospf", "adjacency", "邻接"]},
    {"runbook_id": "rb-flap-001", "fault_type": "route_flap", "device_family": "generic-router", "version": "2026.1", "title": "路由震荡定位", "steps": ["统计前缀更新率", "关联邻居与接口时间线", "路由抑制策略变更必须审批"], "keywords": ["route_flap", "prefix_updates", "震荡"]},
    {"runbook_id": "rb-upstream-001", "fault_type": "upstream_dependency", "device_family": "generic-service", "version": "2026.1", "title": "DNS 与上游依赖排查", "steps": ["分别验证解析和上游连接", "比较多个探测点", "切换上游必须审批"], "keywords": ["dns", "upstream", "依赖"]},
    {"runbook_id": "rb-resource-001", "fault_type": "device_resource", "device_family": "generic-router", "version": "2026.1", "title": "设备资源异常排查", "steps": ["读取 CPU 和内存趋势", "核对最近重启与进程异常", "重启设备或终止进程必须审批"], "keywords": ["cpu", "memory", "资源"]},
    {"runbook_id": "rb-storm-001", "fault_type": "alarm_storm_root", "device_family": "generic-network", "version": "2026.1", "title": "告警风暴根因聚合", "steps": ["按时间窗与拓扑聚合", "优先检查共享上游", "保留下游告警作为影响证据"], "keywords": ["alarm_storm", "related_alarms", "告警风暴"]},
)
