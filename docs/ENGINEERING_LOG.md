# 工程日志

> 记录日期：2026-10-16。本文区分“代码已实现”“本机已验证”“由 CI 设计验证”和“尚未证明”，不把合成结果、静态配置或未运行的 CI 当作生产证据。

## 0. 立项、边界与交付策略

通信网络故障诊断 Agent 被定义为既有 Agent Runtime & Evaluation Platform 的第三个业务适配器，而不是新建一套执行引擎。首版范围固定为 IP 网络和传输链路的 12 类常见故障；所有告警、指标、日志、运维手册和设备工具响应都是项目自建合成内容。

一开始就冻结了以下不能突破的边界：不接入运营商网络或真实网管，不使用来源不明企业日志，不调用真实变更接口，不把本地延迟或合成集准确率描述成生产 SLA。这个选择决定了后续所有“写操作”只会生成审批记录和工单草稿。

交付顺序按 C0–C4 执行：先冻结领域契约，再建立最小诊断链路，接入 Runtime，做数据与安全门禁，最后提供部署拓扑和可视化。

## 1. C0：领域契约与数据边界

### 完成内容

1. 冻结 12 类故障：接口 Down、光功率异常、高 BER、丢包、时延/抖动、高利用率、BGP 邻居中断、OSPF 邻接异常、路由震荡、上游依赖、设备资源异常和告警风暴根因。
2. 为每类故障定义必需/可选观测、易混淆类型、安全动作、必须审批动作和信息不足时的问题。
3. 用 Pydantic 建立严格的告警、指标、事故、证据、根因、处置步骤和工单草稿契约；设备 ID、接口名称、字段数量与文本长度都有约束。
4. 建立工具权限矩阵：L0 手册检索、L1 查询、L2 受预算探测、L3 工单草稿、L4 人工审批；真实变更工具没有被注册。

### 设计取舍

- 首版只覆盖 IP/传输链路，不同时声称覆盖无线、核心网、接入网和所有厂商设备。
- 根因排序使用透明规则基线，而非未经验证的“通信专家模型”；这让每个结论可以检查证据来源。

## 2. C1：最小可审计诊断链路

### 完成内容

1. 实现 9 个确定性合成工具：设备、接口、路由邻居、路径探测、指标、关联告警、手册检索、工单草稿和高风险审批申请。
2. 每个工具都拥有 Pydantic 输入约束、权限标签、超时、类型化故障注入、Runtime Trace、幂等键和合成 fixture。
3. 建立“先证据、后结论”的 Planner：先调用只读工具与手册检索，再产出最多 3 个根因候选、证据引用、处置建议和工单草稿。
4. 高风险动作进入 `waiting_review`；批准后仅写审批记录和草稿，结果中固定记录 `execution_performed=false`；拒绝进入 `failed_closed`。
5. 记录 Prompt Injection 检测和凭据脱敏；手册与日志始终按不可信数据处理，不能改变 Planner 指令。

### 遇到的问题：下游症状压过根因

**现象：** 首次冻结集评测中，接口 Down 与告警风暴场景会被下游“丢包”症状排到更高位置。

**原因：** 初版排序对症状和因果性信号赋予了相近权重，导致高频下游告警掩盖了物理接口状态和上游共因。

**处理：** 在 `diagnosis.py` 中提高接口状态、上游关联和根因告警的因果证据权重；同时把告警与工具返回相矛盾的场景明确转为 `manual_required`，而不是强行选择一个确定结论。

**验证：** 冻结集的 Top-1、Top-3 与证据覆盖门禁恢复通过；这个结果仍只代表对本项目合成契约的正确性。

## 3. C2：复用 Runtime，而不是复制 Runtime

### 完成内容

1. `TelecomIncidentRuntimeAdapter` 复用共享 Runtime 的 Planner Protocol、工具批次、checkpoint、pause/resume、lease、fencing、幂等结果账本和统一 Trace。
2. 本地离线路径使用 SQLite checkpoint 与审计索引；审批恢复、失败关闭、重复工单幂等行为均有测试。
3. 部署模式增加 `PostgresRuntimeBackend` 选择分支，使 Runtime 的 checkpoint、lease 与 fencing 可以落在 PostgreSQL；事故审计索引也有 PostgreSQL 实现。
4. 新增 API：创建、查询、Trace、审核、恢复、手册检索、健康检查、就绪检查和指标端点。

### 遇到的问题：托管 Windows 的 asyncio 无法可靠退出

**现象：** 当前托管 Windows 沙箱中，最小 `asyncio.run()`、`asyncio.sleep(0)`、`asyncio.to_thread()`，以及基于 TestClient 的生命周期，都可能不退出。

**原因判断：** 同样的极小协程与 TestClient 生命周期在未涉及通信业务逻辑时也会卡住，因此判断为宿主异步运行环境问题，而不是 Planner 或工具死循环。

**处理：**

- 仅在 `sys.platform == "win32"` 且未设置 PostgreSQL 时使用 `_WindowsSyntheticRuntime`；
- 用直接 SQLite async-protocol adapter 代替会让出控制权的线程调用；
- 合成 fixture 顺序执行，省去 `asyncio.gather`；
- 保留 lease 获取、fencing 写入与幂等语义，但明确不启动 heartbeat；
- 将依赖完整事件循环生命周期的 HTTP TestClient 测试标为 Windows 跳过，Linux CI 仍执行；正式 Linux/Compose 路径仍使用共享 Runtime 的原生异步批次和 heartbeat。

**证据边界：** Windows 兼容层只能证明离线合成逻辑，不证明并发、heartbeat、跨 Worker 接管或生产恢复能力。

## 4. C3：冻结数据、评测和安全门禁

### 完成内容

1. 生成 `telecom-synthetic-v1`：60 条冻结 JSONL 任务，12 类故障各 5 条；manifest 记录版本、LF 规范化 SHA-256、类别数和合成来源。
2. 建立同一五维口径的 baseline/candidate 成对门禁：Top-1、Top-3、证据、审批策略和注入拒绝，不用不同定义的分数做比较。
3. 实现 14 个确定性故障注入与最终状态断言：工具超时、连接、限流、5xx、无效 JSON、缺字段、语义错误、工具矛盾、无手册、注入、工具预算、审批拒绝和重复工单等。
4. 建立 12 份合成手册的独立 RAG 合同测试：Recall@5、MRR@5、nDCG@5、无答案拒绝和注入拒绝。
5. 添加机器可读发布门禁，检查必需交付物、数据完整性、成对门禁、注入门禁、RAG 门禁、无真实变更 handler 和 Compose 拓扑契约。

### 实际报告结果

- 60/60 成对 Runtime 任务门禁通过；
- 14/14 故障注入通过；
- 合成 RAG 五项指标均为 1.0；
- 数据 SHA-256：`0117eaccded4a4cf2b08fe6b9654d4356e15b27a8e13f6faf5b8fb2aa382e5e9`；
- 发布状态：`ready_with_limitations`。

### 遇到的问题：验证环境不是项目虚拟环境

**现象：** 清理临时目录后，系统 `python` 无法找到 `pytest` 和项目包；一个组合 PowerShell 命令因为最后的 `pip check` 成功而返回了 0，掩盖了前面命令的失败。

**处理：**

- 不把该 0 视作测试通过；
- 使用已存在、包含 FastAPI/pytest 的验证解释器，并通过 `PYTHONPATH` 显式引入本项目和 Runtime 源码；
- 所有后续组合命令在每一步检查 `$LASTEXITCODE`，遇错立即退出；
- 重新执行完整测试、数据生成、manifest 比对、发布门禁和 `pip check`。

**结论：** 这是本机验证环境问题，不是项目依赖已被完整安装的证据；标准可复现安装方式仍以 README 的 `pip install -e ".[dev]"` 和部署模式的 `.[deploy]` 为准。

### 遇到的问题：Git 换行和空白检查

**现象：** 新仓库首次暂存时，`git diff --check` 在大量文本文件报告末尾多余空行，同时 Git 警告 Windows 工作副本将改变 LF/CRLF。

**处理：** 添加 `.gitattributes` 统一文本为 LF，批量机械规范化为单个末尾换行，再以 `git diff --cached --check` 复核。

**结果：** 两次本地提交前均通过差异格式检查；冻结 JSONL 的规范化哈希保持不变。

## 5. C4：服务化交付、Trace 与可观测性

### 完成内容

1. Compose 扩展为六服务：Incident API、Runtime Worker、PostgreSQL、Redis、Prometheus、Grafana。
2. API 在部署模式将事故先写入 PostgreSQL 并返回 `queued`；Redis Worker 读取作业，调用同一 Runtime adapter，随后更新同一审计记录。恢复审批时使用 `queued_resume`。
3. 提供 PostgreSQL 初始化 SQL，其中 `runtime_*` 表归共享 Runtime 所有，`telecom_*` 表归领域适配器所有。
4. 增加 `/ready`、`/metrics` 和无框架 `/trace-ui`。Trace 页面只拼接经过 HTML 转义的数据，不把工具输出直接插入 DOM。
5. 添加 Prometheus scrape 配置、Grafana datasource 和预置 dashboard。
6. GitHub Actions 增加 Linux Compose smoke job：构建六服务、等候 API ready、提交 `incident_optical.json`、轮询 Worker 完成、读取 Trace 与指标。
7. 增加部署契约测试：检查六服务接线、SQL 资产、Grafana JSON、PostgreSQL backend 选择，以及“排队 → 审批 → 恢复”依然不能执行真实变更。

### 遇到的问题：本机没有 Docker

**现象：** `docker` 命令在当前 Windows 主机不存在，无法本机进行镜像构建、`docker compose config` 或六服务启动。

**处理：** 用 YAML/JSON 解析、部署资产契约测试和本地 service/queue 流程测试覆盖静态与代码接线；将真实容器启动和 HTTP smoke 流程写入 Linux CI。

**证据边界：** 当前无法证明 GitHub CI 已实际运行成功，也无法证明本机容器可启动；只能证明 Compose 与 CI 脚本已提交且通过静态/单元级检查。

### 遇到的问题：Windows TestClient 生命周期卡住

**现象：** 增加 `/ready`、`/metrics`、`/trace-ui` 的实际 HTTP 响应测试时，测试在约 20 个断言后卡住，不能退出。

**处理：** 终止卡住测试进程；将该测试限制为非 Windows 执行，并由 Linux CI 与 Compose smoke 覆盖实际 HTTP 调用。本机仍用路由表、服务契约、页面内容和部署配置测试验证接口接线。

## 6. 最终本机验证记录

最后一次本机执行结果：

- `pytest`：23 通过、1 个 Windows 宿主限制跳过；
- `compileall`：通过；
- 数据生成：60 条，manifest SHA-256 匹配；
- 发布门禁：全部检查通过，状态 `ready_with_limitations`；
- Compose YAML 与 Grafana JSON：可解析；
- `git diff --check`：通过；
- Docker：不可用，未执行本机容器测试。

本项目有两个本地提交：

1. `6cc8d88 Build telecom incident diagnosis agent`：C0–C3 和初始交付。
2. `b68b8cf Add deployable telecom runtime topology`：C4 拓扑、Worker、监控、Trace、CI smoke。

## 7. 仍未闭环的事项

1. 在真实 Linux Docker 环境或 GitHub Actions 中查看 Compose smoke 的成功日志并保存链接/工件。
2. 用两个独立 Worker 对 PostgreSQL backend 做本项目级 lease 到期接管与旧 fencing token 拒写的集成测试；不能只依赖 Runtime 上游已有测试。
3. 将 Redis 列表队列升级为带确认/重投和死信策略的可靠队列，覆盖 Worker 在取到任务后崩溃的恢复。
4. 扩充 RAG 评测，补上设备型号过滤、软件版本过滤、过期手册识别、相似错误文档和冲突手册的可量化测试。
5. 用公开且可再分发的标准/厂商资料建立第二套公开语料评测；继续明确它不等价于运营商生产数据。
6. 视目标岗位需要，补全前端 NOC 工作台和人工编辑工单界面；当前 `/trace-ui` 是只读调试页面。

## 8. 简历证据对齐与 V2 评测协议（2026-10-20）

简历审计发现通信项目中存在比当前仓库更大的任务规模和不同指标的表述：仓库 v1
只有 60 条自建合成冻结合同任务，当前结果为确定性契约 100%；它不能直接证明
“240 开发、100 冻结、83%/94%”或“48/40 安全统计”。这不是用 README 文案修饰
能解决的差距，也不能通过事后修改 v1 数据把数字补齐。

处理方式是新增 `RESUME_EVIDENCE_ALIGNMENT.md` 和预注册
`TELECOM_EVALUATION_V2_PROTOCOL.md`：v1 维持不变；v2 将以 240 条开发、100 条
独立冻结的合成任务为目标，并固定 split 隔离、指标定义、48 条越权与 40 条注入
安全 cohort。协议明确不预设准确率，最终简历必须使用机器可读报告的真实结果；若
与旧简历数字不同，更新简历，而不是调数据迎合旧文案。

### 本机验证环境补记

本轮文档/协议测试首先按 README 约定调用 `.venv`，但该仓库当前没有独立虚拟
环境；系统 Python 和 Codex 验证 Python 也没有 pytest。尝试复用 FSO 项目的环境时，
它拥有 pytest 但没有 FastAPI，不能充当本项目的完整依赖环境。该缺口没有被误记为
测试失败或通过：后续完整验证必须在本仓库按 `pip install -e ".[dev]"` 建立隔离环境
后进行。为使文档回归测试不依赖 Windows 终端对中文错误输出的呈现，断言改为稳定的
ASCII 版本/指标标识（`telecom-synthetic-v1`、`83%/94%`、`v2`），仍验证同一证据边界。

首次实现把两个独立 Markdown 数字误断言为连续的 `83%/94%` 字符串；实际文档分别
记录 `83%` 和 `94%`，因此测试改为两个独立断言。该修正只消除测试解析假设，不改变
任何简历或评测数字。

随后按 README 建立项目独立 `.venv` 并执行 `pip install -e ".[dev]"`；固定的
`agent-runtime-quality-platform` 提交、FastAPI、Pydantic、pytest 与项目本身均安装
成功。完整本机基线为 `24 passed, 1 skipped`，并且 `compileall` 与差异空白检查通过。
唯一跳过项仍是既有 Windows HTTP TestClient 生命周期限制；它不等同于 Linux CI 或
Compose HTTP 验收通过，也不影响本轮仅文档/协议的 v2 前置工作。

## 9. GitHub 发布阻塞：远程仓库未配置（2026-10-20）

**现象：** 用户在项目目录执行 `git push origin main` 时收到
`'origin' does not appear to be a git repository`。此前把提交哈希和提交说明直接输入
PowerShell，也产生了 `CommandNotFoundException`。

**排查：** 本地 `git remote -v` 没有任何输出，说明该 checkout 尚未绑定远程；本地
分支为 `main`，最新提交为 `204a429`，作者配置仍为
`KristenYue <yueyt1112@163.com>`。只读查询 GitHub 账号下名称包含
`telecom`、`incident` 或 `network` 的仓库，没有发现可安全复用的现有仓库。

**处理：** 不猜测 GitHub URL，也不自动创建或绑定外部仓库。需要由作者在 GitHub
创建一个空仓库，或明确提供已有仓库 URL；随后在本地执行 `git remote add origin <URL>`
并推送 `main`。提交哈希和提交说明仅用于 Git 记录，不是 PowerShell 命令。

## 10. V2 数据候选包与 split 隔离（2026-10-20）

实现了独立的 `dataset_v2.py`，没有改动 v1 的 60 条冻结任务或它的 manifest。V2
生成器当前可重放地产生：240 条 development 输入、100 条 pre-freeze candidate 输入，
以及独立的 48 条越权工具请求和 40 条提示注入请求。每条诊断样本带有
`family_id`、`template_id`、设备 ID 和时间戳；隔离校验拒绝这四类标识跨 development
与 pre-freeze 两个 split 重叠。所有输入仍为项目自编合成数据，不包含运营商数据。

候选包的 manifest 记录三个 JSONL 的 LF 规范化 SHA-256，但状态固定为
`pre_freeze_candidate_not_evaluation_evidence`。这意味着它尚不能支持“100 条冻结结果”
或任意准确率说法；下一阶段必须审阅 split、封存不可变 manifest，再运行评测并以报告
的实际数字更新简历。

### 遇到的问题：pytest 默认临时目录不可创建

**现象：** 首次运行 V2 测试时，前两项通过，但 pytest 在受控 Windows 沙箱的默认
`AppData` 临时目录创建 `pytest-*` 编号文件夹失败。

**处理：** 不把该环境错误当作测试通过或产品错误；改用仓库受控的
`--basetemp=.pytest-tmp` 后，三项 V2 契约测试通过。后续完整回归也使用同一受控临时
目录，测试临时文件不纳入版本控制。

### 本阶段验证

- V2 数据集契约：3 通过；
- 完整测试：27 通过、1 个既有 Windows HTTP TestClient 生命周期限制跳过；
- `compileall` 与 `git diff --check`：通过；
- 观察到 FastAPI/Starlette 对当前 TestClient 依赖组合的弃用警告。它没有导致失败，
  但在后续依赖升级时需要复核 HTTP 测试兼容性。

## 11. V2 候选封存与实际评测前置（2026-10-20）

V2 封存流程校验候选 manifest 中的 SHA-256、development/pre-freeze 的 split 隔离，
然后将 100 条候选复制为单独的 `telecom_eval_v2_frozen.jsonl`。冻结 manifest 同时保存
源候选和冻结文件的规范化 SHA-256；本次两者均为
`e0acb4eed10dd0186f75f7a2285e3ded919ab76ddd1d4bc3540a50001df217c7`。manifest 状态为
`frozen_input_no_metrics`，明确只证明输入不可变，不证明准确率、安全率或生产表现。

### 遇到的问题：封存测试把说明文字误当作指标

**现象：** 首次封存测试检查 `evidence_boundary` 文本中不能出现 `accuracy`；但正确的
边界说明正是“does not record accuracy”。因此该测试失败，虽然封存脚本已经成功生成并且
哈希一致。

**处理：** 将断言改为检查 manifest 顶层不含 `metrics`、Top-1 或 Top-3 指标字段，而不
对解释性文字做反向关键词匹配。这样测试验证的是实际结构约束，不会惩罚清晰的边界说明。

### 遇到的问题：pre-freeze 注入样本分母为零

**现象：** 第一次对 100 条本地封存输入运行评测时，诊断准确率指标为 1.0，但注入拒绝率
显示为 0.0。排查发现候选生成器只在第 11 个 ordinal 添加恶意日志，而每个 pre-freeze
故障类只有 7 或 9 条，因此冻结输入实际没有任何注入样本。旧评测器使用 `max(1, count)`
规避除零，掩盖了这个分母缺失。

**处理：** 作废该次未提交的本地封存/报告，重新生成候选；每个 pre-freeze 故障类的第 5
条固定包含注入日志，共 12 条。split 校验现在要求 pre-freeze 至少有一条注入样本；评测
报告增加 `metric_denominators.prompt_injection_case_count`，若没有样本则输出 `null`，不再
把“没有测试”表达成 0% 的安全结果。

### 遇到的问题：运行时把未注册工具转换为 ValueError

**现象：** 独立安全 cohort 首次执行时，评测器按内部字典实现预期捕获 `KeyError`，但共享
Runtime 的 `ToolRegistry.resolve()` 将它转换为 `ValueError("tool is not registered: …")`。

**处理：** 改为捕获对外契约的 `ValueError`，而不是依赖 Runtime 的内部字典异常。拒绝
语义保持不变：未注册的 `restart_device` 不能被解析，更不会产生任何工具执行记录。

### 本阶段实际报告

重新生成、封存并运行 100 条输入后，`telecom_eval_v2_frozen_report.json` 记录的实际离线
指标为：Top-1 1.0、Top-3 1.0、证据覆盖 1.0、审批策略 1.0；12 条嵌入式注入样本的拒绝率
为 1.0，报告同时记录该指标分母为 12。结果绑定到冻结输入 SHA-256
`41df471d0a064582f37a614c3e5d39b1f9d345454be4c3252ff1c7edf0979b42`。

独立的 88 条安全 cohort 报告记录：48/48 个未注册危险工具请求被拒绝，40/40 个注入文本
被清洗，工具执行数为 0。这里的授权模型是**工具白名单**，不是用户认证或 RBAC；结论仅适用
项目自编的离线合成输入，不能表示运营商生产安全控制或泛化能力。

完整本机回归为 28 通过、1 个既有 Windows HTTP TestClient 生命周期限制跳过；`compileall`
和差异空白检查通过。仍观察到既有 Starlette TestClient 弃用警告，未影响本轮结果。

## 12. 鲁棒性挑战集与显式别名边界（2026-10-20）

为避免 V2 只在同质的合成输入上取得满分，增加了四项单独的挑战评测：固定的
`vendorx_rx_low` 告警别名、没有可验证信号时转人工、光功率异常与 BGP 中断同时出现、
以及畸形告警在进入 Runtime 前由 Pydantic 拒绝。首次实际运行 4/4 通过，并写出
`telecom_robustness_report_v1.json`。

告警归一化只支持显式列出的三个项目自编别名（VendorX 光功率、VendorY BGP、VendorZ
CPU）；未知厂商告警保持未知，不宣称通用厂商格式兼容。挑战集同样只使用本地确定性工具
和合成输入；它为“何时人工升级/何时入口拒绝”提供证据，但不等价生产鲁棒性。

本阶段完整本机回归为 30 通过、1 个既有 Windows HTTP TestClient 生命周期限制跳过；
`compileall` 与差异空白检查通过。Starlette TestClient 弃用警告仍存在，但没有新增失败。

## 13. 面试证据说明与旧文档状态修正（2026-10-20）

V2 完成后，旧的 V2 协议和简历对齐文档仍保留“尚无 V2 结果”的前置状态，容易让读者误以为
240/100/48/40 均未落地。已更新为指向 candidate/frozen manifest、冻结报告和安全 cohort
报告，并新增 `INTERVIEW_EVIDENCE_CARD.md`：将可说数字、复现命令、不可说的生产结论和常见
追问并列展示。

核对报告时发现共享 Runtime 的 paired gate 中 `success_rate` 是其通用比较口径，不等同通信
业务成功率；该字段在当前报告中不应用于面试表述。证据卡只引用领域评测的 Top-1/Top-3、
证据/审批字段和安全 cohort，并明确它们的合成离线边界。

### 遇到的问题：证据对齐测试仍断言 V2 未完成

**现象：** 更新协议状态后，旧回归测试仍要求出现 `no v2 result exists yet`，导致文档测试
失败。

**处理：** 将测试改为校验“输入已封存并记录离线结果”、协议仍声明非生产 benchmark，且
简历对齐文档同时出现 V2 数值与“项目自建、离线、合成”范围。这样状态变化可被测试覆盖，
也不会删掉核心边界。

## 14. README 首页证据入口（2026-10-20）

README 原先只展示 V1 的 60 条冻结合成合同任务；V2 封存输入、100 条报告、48/40 安全
cohort 与鲁棒性挑战集只能在深层目录发现。首页现增加 V2 独立章节，列出冻结哈希、各报告的
实际离线结果、复现命令和面试证据卡链接；同时在每个容易被误读的安全/指标位置注明“项目自编
合成”“工具白名单而非 RBAC”“非生产泛化或 SLA”。

新增 README 回归测试，确保未来编辑不会只留下百分比而删掉 V2 输入规模、RBAC 边界、合成
范围或面试证据卡入口。

本阶段完整本机回归为 31 通过、1 个既有 Windows HTTP TestClient 生命周期限制跳过；
`compileall` 与差异空白检查通过。既有 Starlette TestClient 弃用警告未造成失败。

## 15. 阶段复盘：Linux Compose 验收证据（2026-10-20）

复核 GitHub Actions 成功运行的 job 级记录后确认：`test-and-gate` 与 `compose-smoke` 均为 success。Compose job 实际完成配置解析、六服务构建/启动、提交一次队列诊断、等待 Worker 完成、读取 Trace/Trace UI/metrics/Prometheus ready，并在结束时清理环境。原计划文档中“尚无 CI 成功运行记录”的表述已过期，已修正并附上运行链接。

这项证据的范围是 Linux CI smoke，不是本机 Docker 验收，也不是生产部署、性能、灾备或运营商系统接入。后续优先级相应调整为 PostgreSQL 双 Worker 接管、Redis 可靠消费、RAG 外部效度和生产化安全演练，而非重复实现已有拓扑。
