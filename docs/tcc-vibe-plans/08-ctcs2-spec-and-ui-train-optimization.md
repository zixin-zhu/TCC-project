# CTCS-2 规范对齐与双站列车演示优化实施计划

> **给执行代理的要求：** 每个阶段开始前先阅读本文件、`docs/IMPLEMENTATION_STATUS.md`、`docs/HANDOFF_交接说明.md` 和相关已有阶段方案；每个阶段必须先补失败测试，再实现代码，阶段验收通过后独立提交并推送。禁止把本仿真软件描述为现场可用的铁路安全设备。

**目标：** 在现有 A/B 双站 CTCS-2 TCC 教学仿真系统基础上，按照所附《客运专线 CTCS-2 级列控系统列控中心技术规范暂行的通知》逐项补齐功能约束，并解决列车演示无法直观观察、无法选择指定列车、列车复位后不能再次操作、日志告警不可按 A/B 分区逐条查看等问题。

**架构：** 两个 TCC 进程/控制器各自维护本地权威状态，通过站间仿真安全信息通道交换边界轨道、方向、闭塞、信号、临时限速和运行状态。UI 只发送命令并显示不可变快照；规则由领域服务和 `TccController` 统一执行。列车演示保留为教学模型，使用一套仿真时钟驱动轨道占用，不模拟真实车载 ATP、测速、应答器物理调制或现场安全通信。

**技术栈：** Python 3.12、PyQt5、Qt `QGraphicsScene/QGraphicsView`、pytest、pytest-qt、SQLite、TCP/IP 本地主机通信、JSON 仿真报文。开发入口是 `/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`，不是外层初始代码目录。

**依据文件：**

- `/Users/zhu/Desktop/TCC-project/技术规范/客运专线CTCS-2级列控系统列控中心技术规范暂行的通知.pdf`（扫描页 4–40；正文、附录 1–3、接口和配置要求）。
- 既有方案：`docs/tcc-vibe-plans/01-foundation-domain.md` 至 `07-integration-delivery.md`。
- 当前交接账本：`docs/HANDOFF_交接说明.md`、`docs/IMPLEMENTATION_STATUS.md`。

---

## 一、规范要求追踪表

扫描 PDF 是图像型文档，以下按文档章节和页码整理为软件可验证要求；不把物理设备指标伪装成 Python 软件已经实现的指标。

| 追踪 ID | 规范要求 | 软件落地点 | 验收证据 |
|---|---|---|---|
| SPEC-01 | TCC 设置于车站、区间中继站及控制无岔站的中继站；每个 TCC 有独立编号 | `configs/` 双站身份、拓扑和边界配置 | 配置校验测试；A/B 身份不重复 |
| SPEC-02 | TCC 与 CBI、CTC、LEU、ZPW-2000(UM) 轨道电路、相邻 TCC、监测系统接口 | `app/network/`、`app/services/` 接口适配层 | 接口状态表、消息类型和故障测试 |
| SPEC-03 | 主要功能包括有源应答器报文调用、轨道电路编码、区间信号点灯、无岔站/进路控制、区间方向与闭塞控制 | `domain/` 服务和控制器事件链 | 正常、占用、故障、分路不良、反向运行矩阵 |
| SPEC-04 | 支持列车双向运行；区间改方必须保证区间空闲、对端无发车进路，不得两端对向运行 | `direction_change.py`、`route_control.py` | 双向改方、并发请求、掉线、占用拒绝测试 |
| SPEC-05 | 轨道区段区分正常占用、故障占用、分路不良；按“占用/出清顺序”判断并防护 | `track_circuit.py`、`shared_track_input.py` | 故障恢复顺序、HU 防护、历史告警测试 |
| SPEC-06 | 轨道电路编码按站内/区间、前方区段、进路状态和方向生成；故障不能保证正确编码时切断编码输出并转离线 | `track_circuit.py`、`signal_control.py` | 码序、频率方向、故障离线测试 |
| SPEC-07 | 应答器报文按进路、临时限速、闭锁状态选取；保存容量至少留 20% 余量；搜索/传输/存储错误必须有防护 | `balise_telegram.py`、`leu.py`、配置目录 | LEU 余量、默认报文、报文错误告警测试 |
| SPEC-08 | 有源应答器覆盖进站、出站、到发线、区间中继等场景；进路解锁后恢复默认报文 | `configs/balise_groups.json`、选择审计 | 正反向组选择、进路解锁恢复测试 |
| SPEC-09 | 临时限速等级至少支持 45/80/120/160/200/250 km/h；管辖范围、制动距离、重叠和更新点必须可追溯 | `temporary_speed.py`、`telegram_packets.json`、UI | 六等级、重叠禁止、撤销/失联保持测试 |
| SPEC-10 | CTC、联锁、LEU、轨道电路、相邻 TCC、信号机和在线测试接口需要统一协议并监视通信状态 | `network/protocol.py`、`InterfaceStatus` | 各接口状态、断链、恢复、计数器测试 |
| SPEC-11 | 设备采用 2 乘 2 取 2 安全冗余、故障自诊断、实时监测、维护测试和报警 | 软件模拟双机结果与诊断层；不声称物理冗余 | 诊断状态、故障降级、告警历史记录 |
| SPEC-12 | 区间信号机灯丝继电器、红灯防护、无岔站信号和进路联动 | `signal_control.py`、线路图/信号页 | HJ/UJ/LJ、红灯、进路状态矩阵 |
| SPEC-13 | CTC/TCC 断链时保持已有限速和报文，不能在断链期间随意改写；相邻 TCC 断链时保持安全方向和默认/既有报文策略 | `peer_sync_service.py`、`temporary_speed.py` | CTC 断链与 TCC 断链分开演练 |
| SPEC-14 | 启动自检、与外部系统按顺序建立通信，并展示启动过程 | `dual_application.py`、全局状态栏 | 启动状态机和可见日志 |
| SPEC-15 | 运行状态、方向、轨道、信号、LEU、限速、对端状态和故障应可监视、记录和查询 | `DualStationSnapshot`、日志页、SQLite | A/B 分区日志逐条显示、持久化回读 |
| SPEC-16 | 课程要求的列车演示要能观察列车跨区段运行以及与轨道码序、信号、应答器的联动 | `DualTrainCoordinator`、新的 2D 场景 | 2D 动画、选中列车、复位后再次发车 |

### 规范边界

以下内容只做“可解释的教学仿真”，不伪造现场能力：

- `2 乘 2 取 2`、SIL4、MTBF、双路电源、光电隔离、EMC 和物理安全通信只在诊断模型、配置和报告中表达，不宣称由 Python/Qt 达到相同安全等级。
- JSON、HEX、CRC32 只称为 `simulation_envelope` 或教学校验，不称为现场应答器 1023 位/830 位物理报文。
- 大号码道岔、CTCS-0 接口和中继站可用最小场景表示，必须在 UI 和报告中标注“仿真简化”。

---

## 二、当前实现审计与必须修改的问题

### 2.1 已有且可复用的能力

- `DualTrainCoordinator` 已有 500 ms 仿真时钟、方向反转遍历、先占用后出清、TRAIN 独立占用源和通信/方向/共享区段安全检查。
- `AlarmService` 已按“告警码 + 来源”去重，支持活动告警和历史告警记录。
- `TccSnapshot` 已包含操作日志、活动告警、轨道、信号、报文、限速和网络指标。
- `configure_combo_box()` 已在 `app/ui/styles.py` 提供按内容测量宽度的基础，可直接复用于列车选择下拉框。
- TCP 帧、握手、心跳、全量同步和故障注入已有测试，不应另起一套网络线程。

### 2.2 现有缺陷和原因

| 缺陷 | 当前原因 | 计划修复 |
|---|---|---|
| 没有列车 2D 运行过程 | `TrainOperationsPage` 只有 `QTableWidget`，协调器只输出数据行 | 新增场景坐标投影和 `QGraphicsView`，用同一 `trains_changed` 信号驱动画面 |
| “发送选中列车”无法稳定选中 | `_selected_train_id()` 依赖表格当前行；刷新行时当前索引可能丢失 | 控制区增加 `QComboBox`，`userData` 保存稳定的 `train_id`，表格只做详情显示 |
| 复位后不能再次发车 | `reset()` 将列车状态设为 `RESET`，而 `dispatch()` 只接受 `WAITING` | 增加 `reset_train(train_id)`，复位后转为可再次派发的 `WAITING`，只清除该列车 TRAIN 来源 |
| 日志告警页没有逐条 A/B 分区 | `DualReadOnlyPage(kind="log")` 只是两行摘要；没有活动/清除历史的逐条模型 | 新增上下分区 `DualLogAlarmPage`，A/B 各自独立表格，统一时间排序和字段 |
| 列车演示容易被全局锁闭误解 | UI 仅显示“联合运行条件”，没有显示具体锁闭原因和列车级状态 | 2D 场景旁显示锁闭原因、列车状态、最后应答器、前方距离和安全状态 |
| 规范里的失联保持、故障占用、分路不良未完整映射到演示 | 当前 `_unsafe_reason()` 只做粗粒度通信/方向/共享状态判断 | 引入状态分类、保护动作、事件日志和测试矩阵 |

---

## 三、目标软件结构

```text
app/
  core/
    enums.py                 # 方向、区段状态、接口状态、列车状态
    models.py                # 不可变快照、日志、告警、限速、列车投影
  domain/
    track_circuit.py         # 占用/出清顺序、编码、故障防护
    signal_control.py        # 信号机、HJ/UJ/LJ、红灯防护
    route_control.py         # 进路和联锁前置条件
    direction_change.py      # 双向改方事务
    balise_telegram.py       # 报文选择、默认报文和教学封装
    leu.py                   # LEU 选择、余量和发送确认
    temporary_speed.py       # 六等级限速、范围、重叠、生命周期
  services/
    tcc_controller.py        # 唯一写入口和事件顺序
    peer_sync_service.py     # 对端快照、全量恢复和新鲜度
    interface_status_service.py # P/Q/R/S/T/U/V/W 接口仿真状态
    train_projection.py      # 区段 -> 线路坐标 -> 2D 绘图数据
    dual_train_coordinator.py# 列车生命周期和 TRAIN 占用
  ui/
    train_scene.py           # 2D 线路、信号、应答器、列车图元
    dual_operations_pages.py # 业务页和列车控制区
    dual_log_page.py         # A/B 上下分区日志告警页
    dual_main_window.py      # 页面装配和快照刷新
    styles.py                # 统一 QSS 和下拉框宽度策略
```

### 3.1 状态分层

```text
LocalAuthorityState
  ├─ 本站轨道区段、信号、进路、LEU、应答器选择
  ├─ 本站故障/人工/列车输入及 state_version
  └─ 本站诊断和操作日志

InterstationAgreement
  ├─ 当前区间方向、闭塞条件、双方版本
  ├─ 请求方/应答方、事务 UUID、阶段和截止时间
  └─ 快照新鲜度、通信健康和联合锁闭原因

PeerSnapshot
  ├─ 对端只读状态和时间戳
  └─ 不能直接写入本地权威状态
```

A/B 不能永久主从。A Server/B Client 只表示教学仿真的 TCP 建链顺序；方向办理时根据当前原发车站和事务方向决定请求方。每个站对本地轨道和设备保持权威，对端只保存互相校验所需的副本。

---

## 四、阶段性实施任务

每个阶段都必须完成：失败测试 → 最小实现 → 定向测试 → 全量回归 → 更新交接文档 → `git commit` → `git push origin codex/dual-station-dashboard`。除文档阶段外，不允许一次跨越多个阶段修改大量代码。

### 阶段 0：规范基线、需求追踪和可中断账本

**目标：** 先冻结规范解释和现状基线，避免后续代理重复判断或把 CTCS-3 逻辑混入 CTCS-2。

**文件：**

- 创建：`docs/ctcs2-spec-traceability.md`，记录本文件 SPEC-01～SPEC-16、PDF 页码、代码文件和测试。
- 创建：`tests/unit/test_spec_traceability.py`，检查每个 SPEC ID 有实现文件和验收测试引用。
- 修改：`docs/IMPLEMENTATION_STATUS.md`、`docs/HANDOFF_交接说明.md`，增加本计划路径、分支、基线测试命令和下一阶段。

**验收：** 文档能由新代理独立定位规范与代码；基线测试命令带 `--basetemp=/tmp/tcc-pytest-bt`，输出保存到交接账本；不得修改业务逻辑。

**Codex 提示词：**

```text
执行 CTCS-2 规范优化阶段 0。先阅读 docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md、现有阶段 1~7、HANDOFF 和 IMPLEMENTATION_STATUS。只建立规范追踪表、失败测试骨架和防中断账本，不改业务代码。逐项核对 PDF 正文、附录 1 区间状态、附录 2 改方、附录 3 临时限速；运行当前全量 pytest，记录真实通过数。完成后提交并推送，更新账本中的 commit、测试输出和下一阶段。
```

**提交：** `docs: add ctcs2 specification traceability baseline`

---

### 阶段 1：双站本地权威状态和 CTCS-2 安全不变量

**目标：** 消除“A 站永久权威、B 站纯投影”的业务歧义；保留 A Server/B Client 的通信启动方式，但让 A、B 都维护本站局部权威状态，方向/闭塞采用双方确认的共享事务。

**文件：**

- 修改：`app/core/models.py`、`app/core/enums.py`。
- 创建：`app/domain/safety_state.py`、`app/domain/interstation_agreement.py`。
- 修改：`app/services/tcc_controller.py`、`app/services/peer_sync_service.py`、`app/ui/dual_snapshot.py`。
- 修改：`app/domain/direction_change.py`、`app/services/direction_change_service.py`。
- 测试：`tests/unit/test_local_authority_state.py`、`test_interstation_agreement.py`、`test_direction_change.py`、`tests/integration/test_direction_change_integration.py`。

**接口：**

```python
@dataclass(frozen=True)
class LocalAuthorityState:
    station_id: str
    tracks: Mapping[str, TrackState]
    signals: Mapping[str, SignalStatus]
    active_route_ids: tuple[str, ...]
    telegram_version: int
    state_version: int

@dataclass(frozen=True)
class InterstationAgreement:
    direction: RunningDirection
    requester_station: str | None
    responder_station: str | None
    phase: DirectionPhase
    transaction_id: str | None
    local_version: int
    peer_version: int
    expires_at_ms: int | None

def can_change_direction(local: LocalAuthorityState,
                         peer: PeerSnapshot,
                         agreement: InterstationAgreement) -> OperationResult: ...
```

**必须实现的规则：**

1. 本站轨道、信号、进路、LEU 选择和故障输入只能由本站控制器写入；远端消息只能形成 `PeerSnapshot`。
2. 改方申请前检查区间所有区段 `CLEAR`，没有 `FAULT_OCCUPIED`、`SHUNT_BAD`、活动发车进路或对向请求。
3. 只有事务 `COMMIT` 后改变方向；`APPROVE` 只能预留，不能切换方向。
4. 站间通信中断时保持已有方向继电器/方向状态，不自动反向；重新握手、全量同步和复核通过后才解除锁闭。
5. 方向由 A→B 或 B→A 对称处理，请求方不写死为 A；“A 站权威”只保留为旧数据迁移兼容字段并标明 deprecated。

**测试重点：** A/B 各自修改本地信号不影响对方权威；正向和反向改方对称；占用、分路不良、故障、冲突进路、超时、重复包、掉线都不能产生两个方向真值。

**提交：** `refactor(safety): model symmetric local authority and interstation agreement`

---

### 阶段 2：轨道状态、编码、信号点灯和附录 1 防护逻辑

**目标：** 将规范中“正常占用/故障占用/分路不良”和“占用出清顺序检查”变成可测试的 CTCS-2 教学规则。

**文件：**

- 修改：`app/domain/track_circuit.py`、`app/domain/signal_control.py`、`app/domain/route_control.py`。
- 修改：`app/services/shared_track_input.py`、`app/services/tcc_controller.py`。
- 创建：`configs/ctcs2_coding_rules.json`、`configs/ctcs2_protection_rules.json`。
- 测试：`tests/unit/test_track_circuit.py`、`test_signal_control.py`、`test_route_control.py`、`test_track_protection_cases.py`。

**技术细节：**

- `TrackState` 至少包括 `CLEAR`、`OCCUPIED`、`FAULT_OCCUPIED`、`SHUNT_BAD`；输入来源仍分为 `TRAIN`、`OPERATOR`、`FAULT`、`SHUNT`。
- 维护区段占用事件序列：列车进入故障区段 → 后方区段出清 → 故障区段出清；只有顺序满足才撤销防护和活动告警。
- 对连续两个及以上闭塞分区的分路不良，向前设置 HU 防护码；列车正常占用并完全出清后才恢复正常码序。
- 区段状态不确定或编码服务故障时，编码输出变为 `OFFLINE`，相关信号保持红灯，不能继续自动改方。
- 站内区段按进路和前方进路状态编码；区间区段按前方占用和前方站接车进路条件编码；正反向遍历使用同一配置规则，不复制第二套 if/else。
- 信号机输出由编码结果、进路、红灯防护和灯丝继电器共同决定，UI 不允许直接写灯色。

**提交：** `feat(ctcs2): add track protection and coding safety rules`

---

### 阶段 3：应答器/LEU、临时限速和断链保持策略

**目标：** 对齐正文 5.2～5.3、5.10～5.12 和附录 3；将临时限速从“普通 CRUD”提升为范围、版本、发送、执行和撤销的可追溯生命周期。

**文件：**

- 修改：`app/domain/balise_telegram.py`、`app/domain/leu.py`、`app/domain/temporary_speed.py`。
- 修改：`configs/telegram_packets.json`、`configs/balise_groups.json`。
- 创建：`configs/ctcs2_tsr_levels.json`、`app/services/telegram_selection_audit.py`。
- 测试：`tests/unit/test_leu_selection.py`、`test_logical_telegram.py`、`test_temporary_speed.py`、`test_ctcs2_tsr_rules.py`。

**技术细节：**

1. LEU 报文存储模型加入 `capacity_total`、`capacity_used`、`reserve_ratio`，强制 `reserve_ratio >= 0.20`；不足时禁止新报文写入并产生告警。
2. 报文选择输入必须包括：方向、进路、临时限速、闭锁、区段状态、应答器组、LEU 端口和状态版本。正常选择、默认回落、选择错误、传输错误、内容存储错误都返回结构化原因。
3. 进站/出站/到发线/中继应答器组按方向配置；进路解锁后回到默认报文；无匹配或 LEU 断联不得返回“成功发送”。
4. 限速等级固定为 `45/80/120/160/200/250 km/h`；`TemporarySpeedArea` 记录起点、终点、制动距离、重叠 80 m、所属 TCC、更新点和当前状态。
5. 约束：临时限速管辖范围从本站进站信号机向前延伸至规定出站口/中继站第二组应答器并附加制动距离；超过 5 个闭塞分区时按区间限速策略拆分；重叠范围禁止重复设置。
6. CTC 断链：保持已执行限速，不允许修改管辖范围；相邻 TCC 断链：保持方向和既有安全报文，按配置回落默认报文，并记录恢复前后的版本。
7. 仿真界面要显示“逻辑字段 / 教学位流 / simulation_envelope”三个层次，不声称生成现场可用 1023 位报文。

**提交：** `feat(ctcs2): enforce telegram capacity and temporary speed lifecycle`

---

### 阶段 4：接口状态、启动自检、诊断和 RAMS 教学模型

**目标：** 将规范 P/Q/R/S/T/U/V/W 接口要求变成统一可观察的仿真接口状态，而不是继续把 TCP 连接状态当成全部业务健康状态。

**文件：**

- 创建：`app/core/interface_models.py`、`app/services/interface_status_service.py`。
- 修改：`app/network/protocol.py`、`app/network/network_worker.py`、`app/dual_application.py`。
- 修改：`app/ui/global_status_bar.py`、`app/ui/dual_operations_pages.py`。
- 测试：`tests/unit/test_interface_status.py`、`test_startup_self_check.py`、`tests/integration/test_interface_failure_recovery.py`。

**接口映射：**

| 接口 | 仿真内容 |
|---|---|
| P | CTC 下发临时限速、列控中心编号、线路号、公用标、设备运行状态 |
| Q | 联锁进路、区间闭塞、轨道占用、改方请求与解锁结果 |
| R | 监测系统读取主备状态、通信端口、LEU、CTC、联锁和轨道电路状态 |
| S | LEU 在线状态、报文发送、发送确认、冗余端口 |
| T | 轨道区段占用、低频/载频码、故障占用、分路不良 |
| U | 相邻 TCC 轨道、信号、方向继电器、临时限速和编码信息 |
| V | 区间信号机、无岔站信号机继电器和点灯显示 |
| W | 在线测试、诊断命令、结果和耗时 |

**启动顺序：** 逻辑运算单元 → 安全输入/输出 → 程序/数据存储 → 轨道电路 → 联锁/CTC → 相邻 TCC → LEU；每一步发出可见事件，失败时进入 `DEGRADED/DISCONNECTED`，不伪造 `HEALTHY`。

**安全模型：** 增加 `DualComputeDiagnostic`，记录主/备计算结果、比较结果、故障定位和降级原因；这是教学可视化，不是 SIL4 认证实现。

**提交：** `feat(diagnostics): expose ctcs2 interfaces and startup self-check`

---

### 阶段 5：列车演示领域模型、2D 线路可视化和可重复列车生命周期

**目标：** 让列车演示从“表格数值变化”升级为可观察的 2D 线路运行过程，并支持选中任意列车、单列车复位后再次发车。

**文件：**

- 修改：`app/services/dual_train_coordinator.py`。
- 创建：`app/services/train_projection.py`、`app/ui/train_scene.py`。
- 修改：`app/ui/dual_operations_pages.py`、`app/ui/styles.py`。
- 测试：`tests/unit/test_dual_train_coordinator.py`、`test_train_projection.py`、`tests/integration/test_train_2d_view.py`。

#### 5.1 列车状态接口

```python
@dataclass
class DualTrainState:
    train_id: str
    direction: RunningDirection
    status: DualTrainStatus
    section_id: str | None
    position_m: float
    current_speed_kmh: float
    target_speed_kmh: float
    distance_ahead_m: float
    last_balise_id: str | None
    safety_state: str
    lifecycle_version: int

def reset_train(self, train_id: str) -> OperationResult: ...
def dispatch(self, train_id: str) -> OperationResult: ...
def start(self, train_id: str | None = None) -> OperationResult: ...
```

#### 5.2 复位后再次操作

- `reset_train(train_id)` 只清除该列车写入的 `TrackInputSource.TRAIN` 占用；如果区段还有人工、故障或分路不良来源，不得强行清空。
- 成功复位后将该列车状态置为 `WAITING`，清空区段、位置、前方距离、速度和最后应答器，保留列车编号，递增 `lifecycle_version`。
- 复位失败时保持 `STOPPED` 和当前区段占用，显示失败原因；不能把状态伪装成可发车。
- `dispatch(train_id)` 接受 `WAITING`，完成进路、方向、通信和入口区段检查后转 `READY`；`start(train_id)` 只启动指定列车，未指定时兼容“所有 READY 列车”。
- 允许多个待发列车；发车前检查同向/反向冲突和前方区段，不能因全局复位清除其他列车的占用。

#### 5.3 2D 可视化技术方案

- 新建 `TrainSceneWidget(QGraphicsView)` 和 `QGraphicsScene`，线路坐标由拓扑配置计算：每个区段拥有 `x_start/x_end`，不硬编码 G01~G08。
- 绘制层：背景与区段层、轨道线路层、信号机层、应答器层、限速/防护标记层、列车图元层、选中高亮层。
- 每个列车图元使用 `train_id` 作为业务 ID；`update_train_projection()` 只更新位置、方向、颜色和标签，不重新创建全部图元，避免闪烁和选择丢失。
- 列车颜色：待发蓝灰、准备绿色、运行蓝色、停车橙色、到达紫色、异常红色；颜色不能替代文字，旁边必须显示状态、区段、速度和安全原因。
- 用 `QTimer` 接收协调器 500 ms 状态，不在 UI 自己推进位置；UI 断开时钟只停止动画，不改变领域状态。
- 鼠标点击列车图元同步 `train_selector`；下拉框改变时同步场景高亮、表格选中行和右侧详情卡。

#### 5.4 控制区改造

在截图所示按钮行加入：

```text
[列车：▼ T001] [添加待发列车] [发送选中列车] [开始仿真]
[暂停仿真] [复位选中列车] [全部复位（需二次确认）]
```

`QComboBox` 使用 `configure_combo_box(combo, "train")`，选项文本为 `T001 · A→B · RUNNING`，`userData` 为稳定的 `train_id`。刷新列车列表时按 ID 恢复当前选项；选中列车不存在时回退到第一列并显示提示。

**提交：** `feat(train): add 2d train scene and repeatable selected-train lifecycle`

---

### 阶段 6：A/B 上下分区日志告警页和逐条事件模型

**目标：** 日志告警页面改为上下两部分，上方固定 A 站，下方固定 B 站，每一条事件单独一行，既能看当前活动告警，也能查看已清除告警和操作历史。

**文件：**

- 创建：`app/ui/dual_log_page.py`。
- 修改：`app/ui/dual_main_window.py`、`app/ui/styles.py`。
- 修改：`app/core/models.py`、`app/services/alarm_service.py`、`app/services/tcc_controller.py`。
- 测试：`tests/unit/test_alarm_service.py`、`tests/unit/test_dual_log_page.py`、`tests/integration/test_dual_main_window.py`。

**数据模型：**

```python
@dataclass(frozen=True)
class LogAlarmRow:
    station_id: str
    event_time_ms: int
    event_type: Literal["操作", "告警", "告警恢复", "系统"]
    level: str
    code_or_operation: str
    source: str
    result: str
    message: str
    state_version: int
    active: bool | None
```

`TccSnapshot` 增加 `alarm_history`；UI 展示 `operation_logs + alarm_history` 的稳定合并结果，按 `event_time_ms` 降序、同时间按插入序号排序。活动告警用红/橙色，已恢复用灰色，但文字必须写明“活动/已恢复”。

**页面布局：**

```text
日志告警
┌────────────── A站 ──────────────┐
│ 时间 | 类型 | 级别 | 代码/操作 | 来源 | 结果 | 说明 | 版本 │
│ ... 每条事件一行，滚动条，最多 200 条 ...             │
├────────────── B站 ──────────────┤
│ 时间 | 类型 | 级别 | 代码/操作 | 来源 | 结果 | 说明 | 版本 │
│ ... 每条事件一行，滚动条，最多 200 条 ...             │
└──────────────────────────────────┘
```

上下区域高度至少各占可用空间 45%，表头固定、列宽可读、长消息支持 tooltip；默认不自动扩大窗口，超过 200 条只保留最新 200 条并在标题显示截断提示。页面不把通信心跳刷新当成业务事件，避免日志无限增长。

**提交：** `feat(ui): split station logs and alarms into row-based panels`

---

### 阶段 7：组合页面、下拉框统一策略和交互一致性

**目标：** 将 2D 场景、下拉选择、日志页和既有双站页面接入同一套快照刷新与 QSS，解决控件短、状态不同步和锁闭原因不可见问题。

**文件：**

- 修改：`app/ui/dual_main_window.py`、`app/ui/dual_operations_pages.py`、`app/ui/station_detail_widget.py`。
- 修改：`app/ui/styles.py`，增加 `COMBO_ROLE_MIN_WIDTHS["train"]` 和表格/场景尺寸策略。
- 测试：`tests/unit/test_ui_styles.py`、`tests/unit/test_ui_operation_gating.py`、`tests/integration/test_dual_operations.py`、`test_dual_dashboard.py`。

**细节：**

- 所有站点、区段、状态、信号、进路、方向、限速、列车下拉框都经过 `configure_combo_box()`；最小宽度由内容实际字体宽度 + 48 px 边距计算，弹出列表不截断。
- `refresh()` 先更新模型，再更新 2D 场景、选择框、表格、按钮；禁止在各页面复制规则或自行修改领域状态。
- 全局安全锁闭时，列车创建、派发、开始、暂停、复位按钮状态一致；安全原因显示为“通信异常/共享区段不一致/方向事务中/故障占用”等具体文本。
- 站间故障演练同时提供 A 链路、B 链路和逻辑对端链路三种入口；后端故障注入仍只作用于网络线程，UI 不直接操作 socket。

**提交：** `fix(ui): integrate train scene selection gating and combo sizing`

---

### 阶段 8：规范场景验收、文档和交付

**目标：** 用可复现的场景证明功能完成，而不是只证明单元测试通过。

**文件：**

- 修改：`docs/DELIVERY_SCENARIOS.md`、`docs/acceptance/DUAL_STATION_FINAL_ACCEPTANCE.md`、`README.md`。
- 创建：`tests/integration/test_ctcs2_spec_scenarios.py`、`docs/acceptance/CTCS2_SPEC_ACCEPTANCE.md`。
- 修改：`docs/IMPLEMENTATION_STATUS.md`、`docs/HANDOFF_交接说明.md`。

**至少验收以下场景：**

1. 启动自检成功、A/B 握手、状态健康、日志分别出现 A/B 启动事件。
2. A→B 正常运行：建路、发车、列车在 2D 线路逐段移动、轨道码序和信号同步变化、经过应答器更新最后应答器。
3. 选择 T001 复位后再次派发、再次启动；T002 保持不受影响；复位失败时保守保留占用。
4. 故障占用和分路不良：产生 HU 防护、红灯和逐条告警；恢复顺序满足后自动撤销防护。
5. 正常改方与辅助改方：区间空闲、无发车进路时成功；占用、冲突进路、通信断链时拒绝并保持方向。
6. 临时限速 45/80/120/160/200/250 km/h：预存、下发、LEU 选择、执行、撤销、重叠禁止和断链保持。
7. LEU 存储不足 20% 余量、报文搜索/传输/存储错误：回落默认报文并在 A/B 日志告警页逐条可见。
8. A 链路和 B 链路分别断开/恢复：两站都能显示接口状态、锁闭原因、重连和全量同步；没有隐藏的“只允许 B 故障”路径。

**交付门：**

- 干净虚拟环境可以安装和启动；
- 全量 pytest 零失败、无 Qt 线程退出警告；
- 2D 场景、列车下拉框、单列车复位重发车、A/B 日志告警截图各一份；
- 报告明确 CTCS-2 实现范围、教学简化和未实现的物理层能力；
- 每个阶段 commit 已推送到 `origin/codex/dual-station-dashboard`，账本记录 commit、测试命令和下一步。

**Codex 提示词：**

```text
执行 CTCS-2 规范优化阶段 8。先阅读本方案全部阶段、IMPLEMENTATION_STATUS、HANDOFF 和 DELIVERY_SCENARIOS。只在前 0~7 阶段全部通过后进行集成验收。按规范场景逐条执行：启动自检、双向运行、占用/故障/分路不良、改方、临时限速、LEU 默认报文、A/B 对称断链、2D 列车选择与复位再发车。保存 pytest 输出、运行日志和界面截图；发现问题先补失败测试再修复。完成后更新报告、账本并提交推送，不能用“测试通过”替代真实场景证据。
```

**提交：** `docs: record ctcs2 specification acceptance evidence`

---

## 五、测试与提交规范

### 5.1 每阶段固定命令

```bash
cd /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
rm -rf /tmp/tcc-pytest-bt
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q --basetemp=/tmp/tcc-pytest-bt
```

GUI 阶段必须额外运行定向测试，例如：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/unit/test_train_projection.py \
  tests/unit/test_dual_log_page.py \
  tests/integration/test_train_2d_view.py \
  --basetemp=/tmp/tcc-pytest-bt
```

### 5.2 每阶段提交模板

```bash
git status --short
git add <本阶段文件>
git commit -m "<阶段约定提交信息>"
git push origin codex/dual-station-dashboard
git log --oneline --decorate -3
```

提交前必须确认：没有 `.venv`、缓存、截图临时文件；测试输出和下一步已写入 `docs/HANDOFF_交接说明.md`；失败测试没有被跳过或标记 xfail 来掩盖。

---

## 六、给后续代理的执行顺序

1. 只做阶段 0，确认规范追踪表和基线测试。
2. 阶段 1 先纠正双站状态语义，再做编码、报文和 UI；否则 2D 场景会继续把 A 站方向误当成全局真值。
3. 阶段 2～4 完成 CTCS-2 规则、接口和故障降级。
4. 阶段 5 处理列车领域和 2D 画面；阶段 6 处理日志；阶段 7 做页面集成。
5. 阶段 8 才进行完整演示和交付，不要在中间阶段宣称“全部完成”。

如果网络或额度中断，下一代理只需读取本文件、`docs/HANDOFF_交接说明.md` 和最近一次提交；从账本中标记为“进行中”的阶段继续，不重复已经有 commit 和测试证据的阶段。
