"""Frozen C0 fault taxonomy and policy boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FaultPolicy:
    code: str
    label: str
    required_signals: tuple[str, ...]
    optional_signals: tuple[str, ...]
    confusable_with: tuple[str, ...]
    safe_actions: tuple[str, ...]
    approval_actions: tuple[str, ...]
    missing_questions: tuple[str, ...]


FAULT_POLICIES: dict[str, FaultPolicy] = {
    "interface_down": FaultPolicy(
        "interface_down", "接口 Down", ("link_down",), ("admin_up", "last_change"),
        ("optical_power_abnormal", "device_resource"),
        ("核对对端与物理连接", "检查接口错误计数"),
        ("restart_interface", "change_interface_config"),
        ("接口名称是什么？", "管理状态是否为 up？"),
    ),
    "optical_power_abnormal": FaultPolicy(
        "optical_power_abnormal", "光功率异常", ("rx_power_low",),
        ("link_flap", "ber_high"), ("interface_down", "high_ber"),
        ("清洁并复核光纤连接", "核对模块与链路预算"),
        ("replace_optic", "shutdown_interface"), ("收发光功率是多少？",),
    ),
    "high_ber": FaultPolicy(
        "high_ber", "高误码率", ("ber_high",), ("crc_errors", "rx_power_low"),
        ("optical_power_abnormal", "packet_loss"),
        ("检查 CRC/BER 趋势", "核对光模块与线路"),
        ("replace_link",), ("误码率时间窗口是什么？",),
    ),
    "packet_loss": FaultPolicy(
        "packet_loss", "丢包升高", ("packet_loss_high",),
        ("queue_drop", "path_probe_loss"), ("high_utilization", "high_ber"),
        ("分段执行只读路径探测", "核对队列丢弃"),
        ("change_qos", "reroute_traffic"), ("丢包发生在哪个方向？",),
    ),
    "latency_jitter": FaultPolicy(
        "latency_jitter", "时延和抖动异常", ("latency_high",),
        ("jitter_high", "hop_delay"), ("high_utilization", "upstream_dependency"),
        ("执行逐跳时延探测", "对齐异常时间窗口"),
        ("reroute_traffic",), ("基线时延是多少？",),
    ),
    "high_utilization": FaultPolicy(
        "high_utilization", "带宽利用率过高", ("utilization_high",),
        ("queue_drop", "traffic_spike"), ("packet_loss", "device_resource"),
        ("确认流量峰值和持续时间", "定位高流量方向"),
        ("rate_limit", "change_qos"), ("链路额定带宽是多少？",),
    ),
    "bgp_neighbor_down": FaultPolicy(
        "bgp_neighbor_down", "BGP 邻居中断", ("bgp_not_established",),
        ("hold_timer_expired", "peer_unreachable"), ("route_flap", "interface_down"),
        ("检查邻居可达性", "核对会话状态和计时器"),
        ("clear_bgp_session", "change_route_policy"), ("邻居地址和 VRF 是什么？",),
    ),
    "ospf_adjacency": FaultPolicy(
        "ospf_adjacency", "OSPF 邻接异常", ("ospf_not_full",),
        ("area_mismatch", "mtu_mismatch"), ("interface_down", "device_resource"),
        ("核对区域、MTU 和 Hello 参数",),
        ("reset_ospf_process", "change_ospf_config"), ("区域和邻居状态是什么？",),
    ),
    "route_flap": FaultPolicy(
        "route_flap", "路由震荡", ("route_change_rate_high",),
        ("neighbor_flap", "prefix_updates"), ("bgp_neighbor_down", "interface_down"),
        ("关联邻居和接口时间线", "定位震荡前缀"),
        ("suppress_route", "change_route_policy"), ("哪些前缀发生震荡？",),
    ),
    "upstream_dependency": FaultPolicy(
        "upstream_dependency", "DNS/上游依赖异常", ("dependency_probe_failed",),
        ("dns_timeout", "upstream_5xx"), ("packet_loss", "latency_jitter"),
        ("查询解析和上游健康状态", "使用备用只读探测"),
        ("switch_dns", "change_upstream"), ("失败域名或上游目标是什么？",),
    ),
    "device_resource": FaultPolicy(
        "device_resource", "设备 CPU/内存异常", ("cpu_or_memory_high",),
        ("process_spike", "control_plane_delay"), ("high_utilization", "route_flap"),
        ("查询资源趋势和最近重启", "定位高占用进程"),
        ("restart_device", "kill_process"), ("资源异常持续多久？",),
    ),
    "alarm_storm_root": FaultPolicy(
        "alarm_storm_root", "多告警风暴根因", ("correlated_upstream_alarm",),
        ("many_downstream_alarms", "shared_timestamp"),
        ("multiple_independent_faults", "interface_down"),
        ("按拓扑和时间聚合告警", "优先核对上游节点"),
        ("bulk_suppress_alarms",), ("这些设备是否共享同一上游？",),
    ),
}

HIGH_RISK_ACTIONS = {
    action
    for policy in FAULT_POLICIES.values()
    for action in policy.approval_actions
}
