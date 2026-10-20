# 通信诊断 Agent：面试证据卡

## 45 秒项目说明

这是共享 Agent Runtime 的通信网络故障诊断适配场景，不是第三套独立平台。输入是项目自建
的合成告警、指标和日志；Agent 先做 Pydantic 校验和注入检测，再并发调用 9 个受控只读/草稿
工具，基于证据排列根因候选。涉及高风险建议时 Runtime 会暂停等待人工审批，批准后也只写审批
记录和工单草稿，不会执行设备变更。每个步骤都有 checkpoint、Trace 与幂等键可回放。

## 有文件支撑的数字

| 主张 | 证据 | 可说边界 |
|---|---|---|
| 12 类故障策略、9 个受控工具 | `taxonomy.py`、`tools.py` | 项目自建合成故障与工具 |
| 240 开发 / 100 冻结输入 | V2 candidate 与 frozen manifest | development 与 SHA-256 封存的合成输入 |
| 100 条冻结输入 Top-1/Top-3 为 100% | `telecom_eval_v2_frozen_report.json` | 确定性规则在自编离线合成集上 |
| 48/48 危险工具未执行；40/40 注入文本清洗 | `telecom_eval_v2_security_cohort_report.json` | 工具白名单和输入清洗，不是 RBAC |
| 4 项挑战集通过 | `telecom_robustness_report_v1.json` | 三个显式别名、人工升级、双故障、畸形输入 |

## 可复现命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp
.\.venv\Scripts\python.exe scripts\evaluate_v2_frozen.py
.\.venv\Scripts\python.exe scripts\evaluate_v2_security_cohorts.py
.\.venv\Scripts\python.exe scripts\evaluate_robustness.py
```

## 面试中主动说明的限制

1. 数据、工具响应、告警别名和运行手册均为项目自编合成内容；没有接入运营商系统。
2. 100% 指标反映规则与自编标签的一致性，不代表真实网络泛化或生产 SLA。
3. 安全评测验证未注册工具的白名单拒绝与注入清洗；项目没有身份认证或 RBAC。
4. Compose/CI 资产存在且 CI 通过；本机未安装 Docker，不能声称本机已完成容器全栈验收。

## 推荐追问回答

**为什么还要保留人工审批？**

网络侧变更风险高，所以 Agent 只能取证、排序和生成草稿；任何高风险动作必须停在
`waiting_review`，拒绝时 `failed_closed`。

**100% 会不会过于理想？**

是的，因此我会先说明它来自冻结的自编合成集。项目把输入哈希、报告、挑战集和局限性同时
提交，下一步重点是独立来源语料和更复杂的失败模式，而不是把这个数字包装成生产效果。
