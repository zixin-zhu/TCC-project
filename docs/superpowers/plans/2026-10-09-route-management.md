# TCC 进路建立与取消功能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 A、B 两站四类接发车进路的建立、冲突校验、取消、锁闭、自动解锁和 UI 操作，并让进路参与列车、信号、编码、应答器及区间改方判断。

**Architecture:** 新增集中式 `RouteService` 作为进路状态的唯一写入点，`MainWindow` 只负责把 UI 操作交给服务并刷新展示。列车、仿真和改方服务通过明确查询接口读取进路状态；2D 绘图只接收进路快照，不保存业务状态。

**Tech Stack:** Python 3.12、PyQt5、`unittest`、现有 QPainter 2D 绘图、现有 TCP 双 TCC 架构。

**Spec:** `docs/superpowers/specs/2026-10-09-route-management-design.md`

## Global Constraints

- 唯一业务依据为 `/Users/zhu/Desktop/TCC整理_可编辑版.docx`，实现正线/侧线接发车、进路建立与取消、无进路禁止发车。
- UI 内部角色保持动态选举，不改变“先启动者为 Server、后启动者为 Client”。
- 区间保持 38 个轨道区段、19 个闭塞分区，每两个轨道区段组成一个闭塞分区。
- 顶部板块顺序固定为“区间改方、进路建立、临时限速”，伸缩比例严格为 `1:2:4`。
- 进路建立、取消和解锁只能通过 `RouteService`；UI 和绘图层不得直接改信号、编码或进路记录。
- `ESTABLISHED` 允许人工取消；`LOCKED` 禁止人工取消，驶过后自动解锁。
- 每个任务测试先行，每个任务完成后更新 `PROGRESS.md`、普通提交并推送；禁止强制推送。

## Review Focus

- 非法站别或进路类型不得创建半条进路；由任务 1 的表驱动异常测试覆盖。
- 同站冲突与两站对向发车竞态不得同时成功；由任务 1 的冲突测试覆盖。
- 锁闭进路的 UI 不得允许取消，直接调用服务也必须失败；由任务 1 和任务 2 双层测试覆盖。
- 复位、一键清车或异常断开后不得遗留进路、信号开放或高亮；由任务 4 和任务 7 覆盖。
- 1180×760 最小窗口下 1:2:4 布局不得裁切，下拉框长文本不得挤压按钮；由任务 2 和任务 7 的尺寸检查覆盖。

---

## 文件职责

- `models/route.py`：进路类型、状态和不可变字段定义。
- `services/route_service.py`：进路建立、冲突、取消、锁闭、释放和查询的唯一业务入口。
- `ui/main_window.py`：进路板块、事件绑定、错误提示和跨服务编排。
- `ui/tcc_overview.py`：按只读进路快照绘制站内进路高亮。
- `services/train_service.py`：发车进路校验、列车绑定、锁闭和自动释放。
- `services/simulation_service.py`：信号及区间边界编码读取进路状态。
- `services/direction_manager.py`：改方的本站发车进路前置和对端发车冲突检查。
- `tests/test_route_service.py`：纯业务状态机与异常输入测试。
- `tests/test_route_integration.py`：列车、信号、应答器、改方联动测试。
- `tests/test_phase1_ui.py`：UI 合同、布局比例和交互测试。

### Task 1: 进路模型与状态服务

**Files:**
- Create: `models/route.py`
- Create: `services/route_service.py`
- Create: `tests/test_route_service.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `RouteType`、`RouteState`、`Route`；`RouteService.establish_route(station: str, route_type: str) -> Route`、`cancel_route(route_id: str) -> bool`、`active_routes(station: str | None = None) -> list[Route]`、`lock_route(route_id: str, train_id: str) -> Route`、`release_route(route_id: str) -> bool`、`clear_all() -> None`。
- Produces queries: `departure_route_for(station: str, track: str) -> Route | None`、`receive_route_for(station: str, track: str) -> Route | None`、`has_departure_route(station: str) -> bool`。

- [ ] **Step 1: 写建立与查询的失败测试**

在 `tests/test_route_service.py` 添加 `test_all_four_route_types_can_be_established_for_each_station`，逐项建立 A/B 两站四类进路并断言显示名、`1G/3G`、`RECEIVE/DEPART` 和初始 `ESTABLISHED` 状态。每个子用例使用新的服务实例，避免同站互斥影响覆盖。

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.venv/bin/python -m unittest tests.test_route_service.RouteServiceTest.test_all_four_route_types_can_be_established_for_each_station -v`

Expected: FAIL/ERROR，提示 `models.route` 或 `services.route_service` 不存在。

- [ ] **Step 3: 实现最小模型和建立查询接口**

在 `models/route.py` 定义四个 `RouteType` 常量、两个 `RouteState` 常量和 `Route` 数据类；在 `services/route_service.py` 使用有序字典保存活动进路，进路编号格式固定为 `<站>-<类型>-<三位序号>`。

- [ ] **Step 4: 运行目标测试并确认通过**

Run: `.venv/bin/python -m unittest tests.test_route_service.RouteServiceTest.test_all_four_route_types_can_be_established_for_each_station -v`

Expected: PASS。

- [ ] **Step 5: 写冲突、异常、取消和锁闭失败测试**

添加以下测试：

- `test_invalid_station_or_route_type_does_not_change_state`；
- `test_same_station_routes_conflict`；
- `test_opposing_departure_routes_conflict`；
- `test_matching_departure_and_remote_receive_can_coexist`；
- `test_established_route_can_be_cancelled`；
- `test_locked_route_cannot_be_cancelled`；
- `test_clear_all_removes_routes_and_resets_sequence`。

断言失败操作前后的 `active_routes()` 完全一致，锁闭取消的中文错误为“列车已进入进路，不能人工取消”。

- [ ] **Step 6: 运行新增测试并确认失败原因正确**

Run: `.venv/bin/python -m unittest tests.test_route_service -v`

Expected: FAIL，缺少冲突、锁闭或清理实现。

- [ ] **Step 7: 实现校验、取消、锁闭、释放和清理**

同站只允许一条活动进路；两站不可同时存在 `DEPART`；`ESTABLISHED` 可取消，`LOCKED` 只允许 `release_route()`；所有异常先校验后写状态。

- [ ] **Step 8: 运行服务测试和完整回归**

Run: `.venv/bin/python -m unittest tests.test_route_service -v`

Expected: 全部 PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 原 17 项及新增测试全部 PASS。

- [ ] **Step 9: 更新进度并提交推送**

Commit: `feat: add route state service`

### Task 2: 进路 UI 与 1:2:4 布局

**Files:**
- Modify: `ui/main_window.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 的 `RouteService` 全部写入和查询接口。
- Produces widgets: `route_station_combo`、`route_type_combo`、`route_establish_button`、`active_route_combo`、`route_cancel_button`。
- Produces methods: `establish_selected_route() -> None`、`cancel_selected_route() -> None`、`refresh_route_controls() -> None`。

- [ ] **Step 1: 写布局和控件合同失败测试**

在 `tests/test_phase1_ui.py` 添加 `test_route_panel_uses_one_two_four_layout_contract`，断言三个 `QGroupBox` 顺序和对象名正确，`operation_top_layout.stretch(0..2)` 分别为 `1, 2, 4`；断言车站选项为 `A站/B站`，进路类型为四种固定中文名称。

- [ ] **Step 2: 写建立与取消交互失败测试**

添加 `test_route_panel_establishes_and_cancels_selected_route`：选择 A站和正线发车，点击建立后活动下拉框含一条记录；点击取消后记录为空、按钮禁用。添加 `test_locked_route_disables_cancel_button`，服务锁闭后刷新并断言取消按钮不可用。

- [ ] **Step 3: 运行 UI 目标测试并确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui.PhaseOneUiContractTest.test_route_panel_uses_one_two_four_layout_contract tests.test_phase1_ui.PhaseOneUiContractTest.test_route_panel_establishes_and_cancels_selected_route tests.test_phase1_ui.PhaseOneUiContractTest.test_locked_route_disables_cancel_button -v`

Expected: FAIL，缺少进路控件或布局仍为 `1:3`。

- [ ] **Step 4: 实现紧凑两行进路板块**

在 `MainWindow.__init__` 创建 `self.route_service = RouteService()`；在 `init_ui()` 中把 `route_management_area` 插入两个已有板块之间。第一行按固定车站宽度、可伸缩进路类型、紧凑“建立”按钮布局；第二行按可伸缩活动进路、紧凑“取消”按钮布局。空状态显示“暂无已建立进路”，控件设置规格中的对象名和工具提示。

- [ ] **Step 5: 实现 UI 事件与原子刷新**

建立或取消成功后调用 `refresh_route_controls()` 和 `refresh_view()`；`ValueError` 分别使用“进路建立失败”“进路取消失败”提示。活动下拉框数据保存 `route_id`，文字格式固定为 `A站｜正线发车｜1G｜已建立`。

- [ ] **Step 6: 运行 UI 测试和完整回归**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui -v`

Expected: 全部 PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 7: 生成两种窗口尺寸截图并检查布局**

生成 1440×900 和 1180×760 截图，确认三个板块等高、比例为 `1:2:4`、按钮不被裁切、下拉框无文字重叠、操作区没有明显空白。

- [ ] **Step 8: 更新进度并提交推送**

Commit: `feat: add route management controls`

### Task 3: 2D 站场进路高亮

**Files:**
- Modify: `ui/tcc_overview.py`
- Modify: `ui/main_window.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `RouteService.active_routes()` 返回的 `Route` 列表。
- Extends: `TccOverviewWidget.set_state(..., routes=None)`。
- Produces: `route_highlight_contract(station: str, route_type: str) -> dict`，供绘图和结构测试共用。

- [ ] **Step 1: 写绘图合同失败测试**

添加 `test_route_highlight_contract_maps_main_and_side_tracks`，断言正线进路映射 `1G` 与对应咽喉，侧线进路映射 `3G` 与对应咽喉；A/B 映射镜像但信号物理方向不变。添加 `test_overview_accepts_active_route_snapshot`，断言 `set_state()` 保存只读快照。

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui.PhaseOneUiContractTest.test_route_highlight_contract_maps_main_and_side_tracks tests.test_phase1_ui.PhaseOneUiContractTest.test_overview_accepts_active_route_snapshot -v`

Expected: FAIL，接口不存在。

- [ ] **Step 3: 实现高亮数据入口与绘制层**

`set_state()` 增加可选 `routes`，默认空列表以保持兼容。`_draw_station()` 在普通钢轨之后、信号和应答器之前绘制浅青白色 4 px 路径；占用红光带最后绘制，优先级高于进路高亮。绘图方法只读取快照。

- [ ] **Step 4: 从主窗口传入活动进路快照**

在 `refresh_view()` 调用 `simulation_view.set_state()` 时增加 `routes=[route.to_dict() ...]`，取消、复位和清车后立即刷新。

- [ ] **Step 5: 运行测试并检查截图**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui -v`

Expected: 全部 PASS。

截图检查四类进路：A正线、A侧线、B正线、B侧线；确认高亮紧贴现有轨道，不覆盖信号名、应答器或区段文字。

- [ ] **Step 6: 更新进度并提交推送**

Commit: `feat: highlight active station routes`

### Task 4: 列车发车、锁闭与自动解锁

**Files:**
- Modify: `models/train.py`
- Modify: `services/train_service.py`
- Modify: `ui/main_window.py`
- Create: `tests/test_route_integration.py`
- Modify: `tests/test_review_corrections.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 的发车进路查询、锁闭和释放接口。
- Changes: `TrainService.__init__(simulation_service, route_service=None)`。
- Changes: `add_waiting_train(departure_mode: str = "MAIN") -> Train`。
- Adds train fields: `departure_mode: str`、`station_track: str`、`route_id: str | None`。

- [ ] **Step 1: 写无进路禁止发车和股道匹配失败测试**

在 `tests/test_route_integration.py` 添加：

- `test_train_does_not_dispatch_without_departure_route`；
- `test_main_train_does_not_use_side_departure_route`；
- `test_matching_departure_route_dispatches_and_locks`。

使用 A_TO_B 时 A 为发车站，正线映射 `1G`、侧线映射 `3G`；成功发车后断言列车 `route_id` 和进路 `LOCKED`。

- [ ] **Step 2: 运行测试并确认旧逻辑错误放行**

Run: `.venv/bin/python -m unittest tests.test_route_integration.RouteTrainIntegrationTest -v`

Expected: FAIL，旧 `TrainService` 无进路仍允许发车或不接受 `route_service`。

- [ ] **Step 3: 实现发车模式和进路校验**

主窗口添加待发列车时把 `departure_mode_combo` 映射为 `MAIN/SIDE`。`can_dispatch_new_train()` 在原自动闭塞条件前检查当前方向发车站对应 `1G/3G` 的有效进路；`dispatch_train()` 成功进入入口区段后锁闭进路并绑定列车。

- [ ] **Step 4: 写自动释放和清理失败测试**

添加：

- `test_departure_route_releases_after_train_enters_second_section`；
- `test_receive_route_locks_at_terminal_section_and_releases_on_arrival`；
- `test_clear_all_trains_and_reset_clear_routes`。

分别覆盖 A_TO_B 和 B_TO_A，避免只实现单方向。

- [ ] **Step 5: 实现生命周期钩子**

在 `handle_track_transition()` 中检测首区段到第二区段并释放发车进路；列车进入运行方向最后一区段时锁闭目的站匹配接车进路，`leave_section()` 后释放。主窗口“一键清车”和“复位”调用 `route_service.clear_all()` 并刷新控件。

- [ ] **Step 6: 更新既有测试夹具并运行完整回归**

只在确实需要无进路发车的旧单元测试中建立匹配进路，不放宽生产规则。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 7: 更新进度并提交推送**

Commit: `feat: enforce route lifecycle for trains`

### Task 5: 信号、编码和应答器联动

**Files:**
- Modify: `services/simulation_service.py`
- Modify: `ui/main_window.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Changes: `SimulationService.__init__(station_type, route_service=None)`，保留默认 `None` 兼容测试。
- Adds: `has_matching_departure_route() -> bool`、`has_matching_receive_route(track: str) -> bool`。
- Consumes: `RouteService` 查询接口，不写进路。

- [ ] **Step 1: 写信号联动表驱动失败测试**

添加 `test_departure_signal_requires_route_direction_and_clear_entry`，覆盖：无进路红灯、方向不符红灯、入口占用红灯、正线发车满足条件按码显示、侧线发车满足条件显示 L 灯特例。

- [ ] **Step 2: 写边界编码与应答器失败测试**

添加 `test_receive_route_extends_boundary_code_target` 和 `test_balise_packets_follow_route_type`，断言无接车进路时边界保持限制码，匹配接车进路建立后升级；侧线进路包含 `ETCS-68` 和 `CTCS-1`，无有效进路保持停车/默认组合，临时限速仍只在实际生效时添加 `ETCS-44(CTCS-2)`。

- [ ] **Step 3: 运行目标测试并确认失败**

Run: `.venv/bin/python -m unittest tests.test_route_integration.RouteSignalIntegrationTest -v`

Expected: FAIL，信号、编码和报文尚未读取进路状态。

- [ ] **Step 4: 实现只读进路注入和统一重算**

`SimulationService.update_signal_status()` 在原方向、占用和码序条件上增加匹配发车进路门控；`update_all_track_codes()` 在运行方向末端读取匹配接车进路调整边界目标。主窗口 `get_balise_information()` 按点击位置所属站和活动进路选择信息包。

- [ ] **Step 5: 运行集成测试和完整回归**

Run: `.venv/bin/python -m unittest tests.test_route_integration -v`

Expected: 全部 PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 6: 更新进度并提交推送**

Commit: `feat: link routes to signalling and balises`

### Task 6: 区间改方进路条件

**Files:**
- Modify: `services/direction_manager.py`
- Modify: `ui/main_window.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Changes: `DirectionManager.__init__(simulation_service, tcc_code, station_type, route_service=None)`。
- Consumes: `RouteService.has_departure_route(station)`。

- [ ] **Step 1: 写改方条件失败测试**

添加：

- `test_direction_request_requires_local_departure_route`；
- `test_direction_request_is_denied_when_remote_departure_route_exists`；
- `test_failed_direction_change_preserves_established_route`；
- `test_valid_route_and_empty_interval_allow_direction_change`。

断言拒绝不会改变两端方向，也不会删除进路。

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `.venv/bin/python -m unittest tests.test_route_integration.RouteDirectionIntegrationTest -v`

Expected: FAIL，旧改方管理器只检查区间、列车和信号。

- [ ] **Step 3: 实现申请方和被申请方进路校验**

`create_request()` 先检查本站发车进路；`evaluate_request()` 根据目标方向推导申请站，拒绝被申请站自身已有发车进路。无 `route_service` 时保持旧构造兼容，但主窗口必须注入真实服务。

- [ ] **Step 4: 运行改方、网络和完整测试**

Run: `.venv/bin/python -m unittest tests.test_route_integration.RouteDirectionIntegrationTest tests.test_network_reconnect -v`

Expected: 全部 PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 5: 更新进度并提交推送**

Commit: `feat: validate routes during direction changes`

### Task 7: 整体视觉与业务验收

**Files:**
- Modify: `docs/TCC功能仿真实现方案.md`
- Create: `docs/phases/PHASE-03.md`
- Modify: `PROGRESS.md`
- Update: `docs/images/phase-03-route-ui.png`
- Update external copy: `/Users/zhu/Desktop/TCC/TCC功能仿真实现方案.md`

**Interfaces:**
- Consumes: Tasks 1–6 的全部功能。
- Produces: 可恢复的阶段 3 技术记录、最终截图和同步方案。

- [ ] **Step 1: 执行完整自动验证**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部测试 PASS，无线程警告或未关闭套接字。

Run: `.venv/bin/python -m py_compile models/route.py services/route_service.py services/train_service.py services/simulation_service.py services/direction_manager.py ui/main_window.py ui/tcc_overview.py`

Expected: 退出码 0。

- [ ] **Step 2: 执行关键业务脚本**

依次验证：A 正线发车、A 侧线发车、B 正线接车、B 侧线接车、未进入取消、进入后拒绝取消、驶过自动释放、无进路禁发、对端发车进路阻止改方、合法改方成功。

- [ ] **Step 3: 检查推荐和最小窗口**

在 1440×900 与 1180×760 下截图。确认 2D 区高度没有明显下降，三个顶部板块比例为 `1:2:4`，进路控件不裁切，长活动进路文本可读，站场高亮紧凑且不遮挡设备。

- [ ] **Step 4: 完成技术文档和恢复入口**

在 `docs/phases/PHASE-03.md` 记录模型、规则、UI、联动、测试结果和截图；在总方案中把阶段 3 标记为完成；在 `PROGRESS.md` 写入最终测试数量、提交和下一原子任务。同步桌面根目录方案副本。

- [ ] **Step 5: 检查改动范围和仓库状态**

Run: `git diff --check`

Expected: 无输出。

确认没有日志模块、固定通信角色回退、区间数量变化或无关文件。

- [ ] **Step 6: 请求整体代码审查并修复问题**

审查重点：进路服务唯一写入、锁闭生命周期、信号/编码一致性、改方双端一致性、UI 最小尺寸和测试是否覆盖真实行为。

- [ ] **Step 7: 提交并推送阶段验收**

Commit: `docs: complete route management phase`

推送后确认 `main...origin/main` 无领先、落后或未提交文件。
