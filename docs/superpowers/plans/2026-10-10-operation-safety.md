# TCC Operation Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 TCC 仿真加入双站通信门禁、方向/进路/限速/列车校验、明确错误弹窗、正确的按钮状态与复位语义，并修复字体和下拉选中项显示。

**Architecture:** 新建纯业务规则模块统一判断方向允许进路及待发列车接发进路匹配；`RouteService` 和 `TemporarySpeedService` 各自维护本领域不变量；`MainWindow` 集中协调通信就绪状态、按钮状态和用户提示。所有业务入口同时具有界面禁用和事件处理函数复检两层保护。

**Tech Stack:** Python 3、PyQt5、`unittest`、现有 TCP/QThread 网络层、QSS。

**Spec:** `docs/superpowers/specs/2026-10-10-operation-safety-design.md`

## Global Constraints

- 唯一需求依据仍为 `/Users/zhu/Desktop/TCC整理_可编辑版.docx` 及用户在本线程确认的修订规则。
- 日志模块不在当前范围。
- 不改变 38 个区间区段、19 个闭塞分区、码序、点灯和应答器信息包规则。
- 初始只有 A/B 两站“启动通信”按钮可用；只有两站都收到 `connected` 后才能操作。
- 错误弹窗必须包含结论、当前状态和处理建议，不显示内部堆栈。
- 复位保留进路和临时限速，锁闭进路恢复为已建立且清空列车绑定。
- 每个任务结束都更新 `PROGRESS.md`，执行普通提交并 `git push origin main`，禁止强制推送。

## Review Focus

- 服务器线程已启动但仍等待客户端时不得提前解锁操作区；Task 4 用单站/双站 `connected` 测试固定。
- 多辆待发列车中任意一辆接发方式不匹配时不得部分启动；Task 5 用第二辆不匹配测试固定。
- 两个限速范围仅相邻而不相交时必须允许；Task 3 用 `G05～G08` 与 `G09～G12` 测试固定。
- 断线时已建立进路、活动限速和列车不得丢失，但引擎必须暂停；Task 4 用状态快照测试固定。
- 复位后的锁闭进路不得残留旧列车编号；Task 2 和 Task 5 分别做服务级与界面级测试。

---

## File Structure

- Create `services/operation_policy.py`: 方向允许表、列车接发进路匹配与结构化业务错误。
- Create `tests/test_operation_policy.py`: 纯规则单元测试。
- Modify `services/route_service.py`: 明确重复/冲突错误，增加锁闭恢复。
- Modify `services/temporary_speed_service.py`: 拒绝活动限速重叠。
- Modify `ui/main_window.py`: 通信就绪集合、统一状态刷新、入口复检、弹窗和复位行为。
- Modify `ui/theme.py`: 公共字体及下拉弹出列表选中色。
- Modify `tests/test_route_service.py`, `tests/test_review_corrections.py`, `tests/test_phase1_ui.py`, `tests/test_route_integration.py`: 回归与集成测试。
- Modify `PROGRESS.md`, `docs/phases/PHASE-03.md`, `docs/TCC功能仿真实现方案.md`: 恢复点和技术说明。

### Task 1: 方向与列车进路规则模块

**Files:**
- Create: `services/operation_policy.py`
- Create: `tests/test_operation_policy.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `OperationRuleError(summary: str, current_state: str, suggestion: str)`；`format_message() -> str`。
- Produces: `OperationPolicy.validate_route_request(direction: str, station: str, route_type: str) -> None`。
- Produces: `OperationPolicy.validate_waiting_train_routes(direction: str, trains: list, route_service: RouteService) -> None`。

- [ ] **Step 1: Write failing rule tests**
  - `test_a_to_b_only_allows_a_departure_and_b_receive`
  - `test_b_to_a_only_allows_b_departure_and_a_receive`
  - `test_waiting_train_requires_matching_departure_and_receive_routes`
  - `test_second_invalid_waiting_train_rejects_whole_batch`
  - Assert `format_message()` includes `操作失败`、`当前状态`、`处理建议` and the train/station/route names.
- [ ] **Step 2: Run RED**
  - Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_operation_policy -v`
  - Expected: FAIL because `services.operation_policy` does not exist.
- [ ] **Step 3: Implement the interfaces**
  - Use literal direction table: `A_TO_B -> A/DEPART, B/RECEIVE`; `B_TO_A -> B/DEPART, A/RECEIVE`.
  - Validate every waiting train using its stored `departure_mode` and `arrival_mode`; collect no partial state.
- [ ] **Step 4: Run GREEN and full suite**
  - Run the target command, then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`.
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: add operation safety policy`

### Task 2: 进路错误与复位解锁

**Files:**
- Modify: `services/route_service.py`
- Modify: `tests/test_route_service.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: existing `Route`, `RouteState`, `RouteType`.
- Produces: `RouteService.reset_locks() -> None`.
- Produces: distinct `ValueError` messages for duplicate route, same-station conflict, opposing departure conflict and locked cancellation.

- [ ] **Step 1: Write failing service tests**
  - Exact duplicate must mention station and display name plus “请勿重复操作”.
  - Different same-station route must mention both existing and requested route.
  - Locked cancellation must mention bound `train_id`.
  - `reset_locks()` must preserve route IDs/order, set every route to `ESTABLISHED`, and set `train_id` to `None`.
- [ ] **Step 2: Run RED**
  - Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_route_service -v`.
- [ ] **Step 3: Implement minimal service changes**
  - Check exact duplicate before generic same-station conflict; do not alter route creation order on failure.
- [ ] **Step 4: Run target and full suite**
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: clarify route conflicts and reset locks`

### Task 3: 临时限速重叠冲突

**Files:**
- Modify: `services/temporary_speed_service.py`
- Modify: `tests/test_review_corrections.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `TemporarySpeedService.find_overlap(start_section: str, end_section: str) -> dict | None`.
- Changes: `set_restriction(...)` raises `ValueError` containing proposed and existing restriction details before allocating a new ID.

- [ ] **Step 1: Replace old overlap-takes-lower test with failing conflict tests**
  - Overlap `G05～G10` plus `G08～G12` fails and preserves one active restriction.
  - Exact duplicate range fails.
  - Adjacent `G05～G08` and `G09～G12` succeeds.
  - Failed insert does not consume the next `TSR-NNN` number.
- [ ] **Step 2: Run RED**
  - Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_review_corrections.TemporarySpeedServiceTest -v`.
- [ ] **Step 3: Implement closed-interval overlap detection**
- [ ] **Step 4: Run target and full suite**
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: reject overlapping speed restrictions`

### Task 4: 双站通信门禁与断线保护

**Files:**
- Modify: `ui/main_window.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `OperationRuleError.format_message()` from Task 1.
- Produces: `MainWindow.communication_ready() -> bool`.
- Produces: `MainWindow.require_communication(title: str) -> bool`.
- Produces: `MainWindow.refresh_control_states() -> None`.
- State: `MainWindow.connected_stations: set[str]`.

- [ ] **Step 1: Write failing UI tests**
  - Initial state: only two start-communication buttons enabled.
  - Starting one fake worker without `connected.emit()` keeps operations disabled.
  - Emitting both connected signals unlocks operations.
  - Disconnect pauses an active engine, disables operations, and preserves trains/routes/restrictions.
  - Directly calling a guarded business handler before connection shows complete communication error and changes no state.
- [ ] **Step 2: Run RED**
  - Run named tests in `tests.test_phase1_ui.PhaseOneUiContractTest`.
- [ ] **Step 3: Implement centralized communication state**
  - `is_connected()` delegates to `communication_ready()`; `on_connected` adds station; disconnect clears set and pauses engine.
  - Call `refresh_control_states()` after init, network events and view refreshes.
- [ ] **Step 4: Run target and full suite**
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: gate operations on station communication`

### Task 5: 仿真启动校验、按钮状态与复位语义

**Files:**
- Modify: `ui/main_window.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `OperationPolicy.validate_waiting_train_routes(...)` and `RouteService.reset_locks()`.
- Produces: `MainWindow.show_operation_error(title: str, error: OperationRuleError | str) -> None`.
- Produces: `MainWindow.validate_simulation_start() -> bool`.

- [ ] **Step 1: Write failing lifecycle tests**
  - Empty queue start shows `仿真启动失败` and timer stays stopped.
  - Mismatched departure route, mismatched receive route and missing route each show train ID/current/required route.
  - Fully matching A→B and B→A cases start the timer.
  - While running pause/reset enabled and start disabled; after pause the inverse applies.
  - Clear enabled only for non-empty waiting queue; cancel TSR enabled only with an active selected restriction.
  - Reset clears trains/time/occupancy, preserves restrictions/routes, and restores locked routes to established without `train_id`.
- [ ] **Step 2: Run RED**
- [ ] **Step 3: Implement validation and state transitions**
  - Validate the complete waiting batch before `engine.start()`.
  - Remove `route_service.clear_all()` from reset and clear-train paths; call `reset_locks()` only from reset.
  - Route, TSR, train and simulation handlers finish by calling `refresh_control_states()`.
- [ ] **Step 4: Run target and full suite**
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: enforce simulation lifecycle rules`

### Task 6: 完整错误弹窗与方向进路集成

**Files:**
- Modify: `ui/main_window.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 direction validation and structured messages; Task 2/3 service errors.
- Produces: all route/TSR/start errors through `show_operation_error(...)`.

- [ ] **Step 1: Write failing popup tests using real services**
  - A→B rejects B departure and A receive; B→A rejects A departure and B receive.
  - Duplicate route popup names the existing route and recovery action.
  - Overlapping TSR popup names both ranges, both speeds and conflicting ID.
  - Every captured warning body includes all three standardized sections.
- [ ] **Step 2: Run RED**
- [ ] **Step 3: Route all expected validation failures through the common formatter**
- [ ] **Step 4: Run target and full suite**
- [ ] **Step 5: Update progress, commit and push**
  - Commit: `feat: add complete operation error dialogs`

### Task 7: 字体、下拉菜单与最终验收

**Files:**
- Modify: `ui/main_window.py`
- Modify: `ui/theme.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`
- Modify: `docs/phases/PHASE-03.md`
- Modify: `docs/TCC功能仿真实现方案.md`
- Update: `docs/images/phase-04-panel-polish-1440x900.png`
- Update: `docs/images/phase-04-panel-polish-1180x760.png`

**Interfaces:**
- Consumes: completed state machine and existing 1:4:5 responsive layouts.
- Produces: uniform inherited font and readable `QComboBox QAbstractItemView` states.

- [ ] **Step 1: Write failing style/layout tests**
  - Route/TSR labels and combos inherit the application font size rather than local `10px/11px` overrides.
  - Stylesheet contains explicit popup `color`, `background`, `selection-color` and `selection-background-color` values with contrast.
  - 1180×760 controls remain at least their `minimumSizeHint()` and do not overlap.
- [ ] **Step 2: Run RED**
- [ ] **Step 3: Remove local font overrides and add popup-view QSS**
  - Preserve `1:4:5`; adjust row spacing/minimum widths only as required by screenshot evidence.
- [ ] **Step 4: Run final verification**
  - `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`
  - `.venv/bin/python -m py_compile services/operation_policy.py services/route_service.py services/temporary_speed_service.py ui/main_window.py ui/theme.py`
  - `git diff --check`
  - Render and inspect 1440×900 and 1180×760 screenshots, including an opened combo popup when platform automation permits.
- [ ] **Step 5: Update all docs and desktop plan copy**
  - Sync `docs/TCC功能仿真实现方案.md` to `/Users/zhu/Desktop/TCC/TCC功能仿真实现方案.md` and verify byte equality.
- [ ] **Step 6: Commit and push**
  - Commit: `fix: complete operation safety workflow`

