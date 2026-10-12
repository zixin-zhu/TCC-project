# Station Path, Signal Synchronization and Full Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让多辆待发列车以单一 xN 标记显示，列车从站内待发点沿正线或侧线连续驶入区间，所有信号严格跟随轨道码序和安全条件，并让全局复位清除全部进路与列车接发方式。

**Architecture:** `Train` 和 `TrainService` 负责 `DEPARTING` 领域状态及站内连续进度，`TccOverviewWidget` 只根据统一站场几何合同把进度映射到正线或侧线折线路径。`SimulationService` 作为轨道码序到信号显示的唯一业务来源，`MainWindow` 只负责组合快照、纯文本展示与复位后的同步刷新。

**Tech Stack:** Python 3.12、PyQt5、`unittest`、Qt offscreen 渲染、Git

**Spec:** `docs/superpowers/specs/2026-10-12-station-path-signal-reset-design.md`

## Global Constraints

- 保留 38 个区间轨道区段、19 个闭塞分区以及每两个区段共享一个闭塞分区编码的现状。
- 发车仍只作用于“查看列车”当前选中的一辆待发列车。
- 待发列车只绘制一个车体，标签 `xN` 中的 `N` 是该出发端待发列车总数。
- A→B 从 A站 X 信号机右侧起步并进入 G01；B→A 从 B站 S 信号机左侧起步并进入 G38。
- 侧线运动必须按折线累计长度插值，禁止用横坐标比例制造纵向跳变。
- `L5/L4/L3/L2/L → 绿灯`、`LU → 黄绿灯`、`U → 黄灯`、`HU/未知 → 红灯`、`UUS → L灯`。
- 没有合法进路、方向不允许或防护区段占用时，安全门控优先显示红灯。
- 复位删除全部发车和接车进路，清空列车接发方式和进路绑定，但保留临时限速及每辆列车设置的最大速度。
- UI 保持现有 1:4:5 操作板块比例、黑色连续站场和 1600×760 下无文字覆盖。
- 每项任务完成后更新 `PROGRESS.md`，执行专项测试、全量测试和 `git diff --check`，随后提交并推送 `main`。

## Review Focus

- 两个方向同时存在待发列车时：每个出发端各显示一个独立的 `xN`，不能把两个方向合并计数；由 Task 2 的双方向标记测试覆盖。
- 多辆运行列车的一个时钟周期：每辆列车只能更新一次，不能因嵌套遍历重复推进；由 Task 1 的多车单步距离测试覆盖。
- 侧线列车暂停后恢复：恢复位置必须仍落在同一折线段，不能回正线或跳至 3G；由 Task 2 的暂停恢复路径测试覆盖。
- 码序为空、非法或信号所防护方向不开放：信号必须降级为红灯，不能沿用旧灯色；由 Task 3 的故障安全测试覆盖。
- 复位时既有未锁闭进路和其他列车锁闭进路：必须全部删除，UI 选择框及列车文字状态必须同步清空；由 Task 4 的混合进路复位测试覆盖。

---

## File Structure

- `models/train.py`：保存列车阶段、接发方式、进路绑定和站内连续进度；提供进入发车阶段与彻底复位的原子方法。
- `services/train_service.py`：校验发车条件、推进 `DEPARTING`/区间/接车阶段、处理进路释放、同步占用与多车单步更新。
- `services/simulation_service.py`：集中维护码序—灯色表，生成区间及本站全部信号机状态快照。
- `ui/tcc_overview.py`：维护站场几何合同、折线长度插值、单一待发数量标记以及按信号快照绘制。
- `ui/main_window.py`：组合 A/B 站和区间信号快照、执行全局复位、刷新纯文本列车状态。
- `ui/theme.py`：移除三项只读状态的输入框式边框、背景和内边距。
- `tests/test_multi_train_dispatch.py`：覆盖领域状态机、多车更新、进路释放与复位规则。
- `tests/test_route_integration.py`：覆盖码序到信号的业务映射及门控。
- `tests/test_phase1_ui.py`：覆盖待发标记、折线路径、信号快照、纯文本样式和全局 UI 复位。
- `docs/phases/PHASE-06-STATION-PATH-SIGNAL-RESET.md`：记录最终实现、验收命令、截图和中断恢复入口。
- `PROGRESS.md`：每项任务实时登记当前原子步骤、验证结果和最新提交。

### Task 1: 发车阶段与多车单步推进

**Files:**
- Modify: `models/train.py:1-225`
- Modify: `services/train_service.py:94-505`
- Modify: `tests/test_multi_train_dispatch.py:85-400`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `RouteService.lock_route(route_id: str, train_id: str) -> Route`、`TrainService.get_entrance_track(direction: str) -> str`
- Produces: `Train.enter_departure(route_id: str, track: str, initial_position: float = 0.0) -> None`、`TrainService.handle_departure_transition(train: Train) -> None`，以及状态快照中的 `movement_phase="DEPARTING"` 和 `station_position: float`

- [ ] **Step 1: 写出发阶段失败测试**

在 `MultiTrainLifecycleTest` 增加 `test_dispatch_starts_at_station_before_entrance_section`：建立 A站正线发车进路并发出选中列车后，断言状态为 `RUNNING`、阶段为 `DEPARTING`、`current_track is None`、`station_position == 0.0`、发车进路为 `LOCKED`。

- [ ] **Step 2: 运行测试确认当前实现失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainLifecycleTest.test_dispatch_starts_at_station_before_entrance_section -v`

Expected: FAIL，当前实现会立即进入 `G01`/`G38` 并释放发车进路。

- [ ] **Step 3: 为 Train 增加发车阶段入口**

在 `models/train.py` 实现 `enter_departure(route_id: str, track: str, initial_position: float = 0.0) -> None`：设置 `departure_route_id`、`route_id`、`station_track`、`station_position`、`position`、`status="RUNNING"`、`movement_phase="DEPARTING"`，不设置 `current_track`。

- [ ] **Step 4: 修改发车提交逻辑**

在 `TrainService.dispatch_train(train: Train) -> bool` 中先锁闭匹配进路，再调用 `train.enter_departure(...)`；删除立即 `enter_track()`、立即读入口应答器和立即释放发车进路的行为。

- [ ] **Step 5: 写双方向越站界测试**

增加 `test_departing_enters_g01_or_g38_only_after_station_boundary`，分别验证 A→B/B→A 在 `station_position < STATION_EXIT_POSITION` 时不占区间，到达边界后进入 `G01/G38`、读取入口应答器并删除已使用发车进路。

- [ ] **Step 6: 实现发车阶段推进与越界**

在 `TrainService.update_train(train: Train, delta_time: float) -> None` 纳入 `DEPARTING`；实现 `handle_departure_transition(train: Train) -> None`，越过 `STATION_EXIT_POSITION` 时保留超出距离进入入口区段、调用 `read_passive_balise()`、释放发车进路并重新计算速度。

- [ ] **Step 7: 写多车单步更新回归测试**

增加 `test_each_running_train_advances_once_per_update_all_tick`：两辆列车以相同初始速度运行一次 `update_all(1.0)`，断言每辆距离增量等于单次 `Train.update(1.0)` 的结果，而不是列车数量倍数。

- [ ] **Step 8: 修复运行列车集合构造**

在 `TrainService.update_all(delta_time: float)` 中移除重复的嵌套 `for train in self.trains.values()`，保证每辆 `RUNNING` 列车只进入一次排序列表。

- [ ] **Step 9: 运行 Task 1 专项与全量测试**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 10: 更新进度并提交上传**

在 `PROGRESS.md` 记录 Task 1 的状态机、专项/全量测试结果和下一恢复入口。

```bash
git add models/train.py services/train_service.py tests/test_multi_train_dispatch.py PROGRESS.md
git commit -m "feat: add continuous station departure phase"
git push origin main
```

### Task 2: 单一待发数量标记与站内折线路径

**Files:**
- Modify: `ui/tcc_overview.py:207-300, 336-495, 920-971`
- Modify: `tests/test_phase1_ui.py:181-215, 408-730`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 输出的 `movement_phase`、`station_position`、`station_track`、`arrival_track`
- Produces: `TccOverviewWidget.station_train_path(station: str, direction: str, track: str, rail_y: float) -> tuple[tuple[float, float], ...]`、`TccOverviewWidget.interpolate_path(points, progress: float) -> tuple[float, float]`、`TccOverviewWidget.waiting_marker_contracts(trains: list[dict]) -> tuple[dict, ...]`

- [ ] **Step 1: 写单一 xN 标记失败测试**

增加 `test_waiting_markers_aggregate_by_departure_end`：传入三辆 A→B 和两辆 B→A 待发列车，断言只返回两个标记，分别是 A站 X 右侧 `x3` 和 B站 S 左侧 `x2`。

- [ ] **Step 2: 运行测试确认当前实现失败**

Run: `.venv/bin/python -m unittest tests.test_phase1_ui.PhaseOneUiContractTest.test_waiting_markers_aggregate_by_departure_end -v`

Expected: FAIL，当前实现为每辆待发列车生成一个逐渐偏移的车体。

- [ ] **Step 3: 实现按出发端聚合的标记合同**

实现 `waiting_marker_contracts(trains: list[dict]) -> tuple[dict, ...]`，只统计 `status == "WAITING"`；修改 `_draw_train_markers()` 先绘制聚合标记，再跳过单车 WAITING 绘制。

- [ ] **Step 4: 写正线与侧线路径几何测试**

增加 `test_station_train_paths_use_signal_endpoints_and_turnout_slopes`：四种方向/正侧线组合的起终点必须对应 X/S/SN，正线所有 y 相同，侧线必须包含“正线—斜坡—3G—斜坡—正线”五段。

- [ ] **Step 5: 写按长度插值测试**

增加 `test_side_path_interpolation_lands_on_each_slope`：选取累计长度落在左右斜坡的两个进度，断言 x、y 同时位于对应端点之间；另断言 progress 小于 0 和大于 1 时夹紧到路径首尾。

- [ ] **Step 6: 实现统一站场路径与插值**

在 `ui/tcc_overview.py` 基于 `station_geometry_contract()`、传入的 `rail_y`、派生的 `side_y`、`siding_left/right`、`main_left/right_throat` 实现 `station_train_path(...)` 和 `interpolate_path(...)`，反方向只反转同一组路径点。

- [ ] **Step 7: 接入发车和接车阶段绘制**

扩展 `train_marker_contract()` 与 `_draw_train_markers()`：`DEPARTING` 使用出发站及 `station_track`，`RECEIVING/STATION_RUNNING/EXITING` 使用到达站及 `arrival_track`；两者均按 `station_position / STATION_EXIT_POSITION` 沿折线长度绘制。

- [ ] **Step 8: 写暂停恢复位置回归测试**

增加 `test_paused_side_train_keeps_same_interpolated_position`：同一侧线列车在 `RUNNING` 与 `STOPPED` 快照下生成完全相同的绘制坐标。

- [ ] **Step 9: 运行 Task 2 专项与全量测试**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 10: 更新进度并提交上传**

```bash
git add ui/tcc_overview.py tests/test_phase1_ui.py PROGRESS.md
git commit -m "feat: render aggregated waiting trains and station paths"
git push origin main
```

### Task 3: 轨道码序驱动全部信号机

**Files:**
- Modify: `services/simulation_service.py:8-25, 430-580`
- Modify: `ui/main_window.py:1224-1301`
- Modify: `ui/tcc_overview.py:86-99, 311-334, 435-457, 629-687`
- Modify: `tests/test_route_integration.py:90-190`
- Modify: `tests/test_phase1_ui.py:650-730, 1605-1630`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `SimulationService.get_station_track_codes() -> dict[str, str]`、`RouteService.active_routes(station: str | None = None) -> list[Route]`
- Produces: `SimulationService.aspect_for_code(code: str | None) -> str`、`SimulationService.get_station_signal_aspects() -> dict[str, str]`、`SimulationService.get_interval_signal_aspects() -> dict[str, str]`；`TccOverviewWidget.set_state(..., station_signals: dict[str, dict[str, str]] | None = None, interval_signals: dict[str, str] | None = None)`

- [ ] **Step 1: 写唯一灯色映射失败测试**

在 `tests/test_route_integration.py` 增加 `test_aspect_for_code_covers_all_codes_and_fails_safe`，逐项断言 `L5/L4/L3/L2/L` 为绿灯、`LU` 为黄绿灯、`U` 为黄灯、`HU/None/非法值` 为红灯、`UUS` 为 L灯。

- [ ] **Step 2: 运行映射测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_route_integration.RouteSignalIntegrationTest.test_aspect_for_code_covers_all_codes_and_fails_safe -v`

Expected: FAIL，尚无公开的统一 `aspect_for_code()` 接口或未知值未按红灯处理。

- [ ] **Step 3: 集中码序—灯色规则**

在 `SimulationService` 将 `CODE_ASPECTS` 作为唯一映射，新增 `aspect_for_code(code: str | None) -> str`，让既有 `get_aspect_by_code()` 调用该接口或作为兼容别名。

- [ ] **Step 4: 写站内信号快照测试**

增加 `test_station_signal_aspects_follow_selected_route_code_and_gate`：无进路全部红；正线进路只允许对应 X1/S1 与外方信号按 `1G/THROAT` 映射；侧线进路只允许对应 X3/S3 按 `3G=UUS` 显示 L灯；方向不符、入口占用均红。

- [ ] **Step 5: 实现本站信号快照**

实现 `get_station_signal_aspects()`：先创建本站六架信号全红字典，再依据当前方向、唯一活动进路、`get_station_track_codes()` 和占用门控只开放该进路使用的内方与外方信号。

- [ ] **Step 6: 写区间信号快照测试**

增加 `test_interval_signal_aspects_follow_protected_block_codes`：A→B 时 S01～S18 读取其前方所防护闭塞分区当前最限制码；切换为 B→A 后这些固定向右信号全部红；受保护区段占用或未知码时为红。

- [ ] **Step 7: 实现区间信号快照**

实现 `get_interval_signal_aspects()`：输出 `S01`～`S18`；每架固定向右信号取下一闭塞分区两个物理区段中的最限制码并调用 `aspect_for_code()`，非 A→B 方向统一红灯。

- [ ] **Step 8: 写绘图层消费快照测试**

在 `tests/test_phase1_ui.py` 增加 `test_overview_draws_supplied_station_and_interval_signal_aspects`，向 `set_state()` 注入不同灯色后离屏绘制，断言记录的信号符号状态与快照一致，且未提供/缺键时为红灯。

- [ ] **Step 9: 接入 MainWindow 与 TccOverviewWidget**

`MainWindow.refresh_view()` 分别从 A/B `SimulationService` 取得站内信号快照，从 A侧取得区间信号快照；`TccOverviewWidget` 保存并绘制这些状态，删除 `_draw_interval()` 中写死的“绿灯”和 `_draw_station()` 只处理 SN/X 的分支。

- [ ] **Step 10: 运行 Task 3 专项与全量测试**

Run: `.venv/bin/python -m unittest tests.test_route_integration -v`

Expected: PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 11: 更新进度并提交上传**

```bash
git add services/simulation_service.py ui/main_window.py ui/tcc_overview.py tests/test_route_integration.py tests/test_phase1_ui.py PROGRESS.md
git commit -m "feat: drive all signals from track codes"
git push origin main
```

### Task 4: 纯文本状态栏与全进路复位

**Files:**
- Modify: `models/train.py:120-155`
- Modify: `services/train_service.py:250-280`
- Modify: `ui/main_window.py:495-525, 1183-1219, 1528-1620`
- Modify: `ui/theme.py:91-99`
- Modify: `tests/test_multi_train_dispatch.py:235-290`
- Modify: `tests/test_phase1_ui.py:73-90, 900-970, 1170-1205`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `RouteService.clear_all() -> None`、Task 1 的 `Train.reset_to_departure(preserve_configuration: bool)`
- Produces: `TrainService.reset_dispatched_trains(clear_routes: bool = True) -> list[Train]`，复位后所有列车 `departure_mode/arrival_mode/station_track/arrival_track/route_id/departure_route_id/receive_route_id is None`

- [ ] **Step 1: 写混合进路全复位失败测试**

在 `tests/test_multi_train_dispatch.py` 改写复位测试：准备已锁闭发车进路、已锁闭接车进路和未锁闭预建进路，执行 `reset_dispatched_trains()` 后断言 `route_service.active_routes() == []`、所有运行/暂停/到达列车回到 WAITING、所有接发方式和进路字段为空、最大速度保留。

- [ ] **Step 2: 运行领域复位测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainLifecycleTest.test_pause_resume_and_reset_apply_to_all_dispatched_trains -v`

Expected: FAIL，当前实现保留进路和接发方式。

- [ ] **Step 3: 实现彻底列车复位与清空进路**

让 `TrainService.reset_dispatched_trains(clear_routes: bool = True)` 对运行、暂停、已到达列车调用 `reset_to_departure(preserve_configuration=False)`，随后调用 `RouteService.clear_all()`；保证原有 WAITING 列车不丢失且待发队列不重复。

- [ ] **Step 4: 写 MainWindow 复位同步测试**

在 `tests/test_phase1_ui.py` 改写 `test_reset_returns_all_dispatched_trains_and_clears_every_route`：复位后断言进路下拉框为空、取消按钮失效、当前选中列车显示“发车进路尚未建立”“接车进路尚未建立”“待发”，临时限速仍在，2D 活动进路快照为空。

- [ ] **Step 5: 接入复位刷新顺序**

在 `MainWindow.reset_simulation()` 中按“暂停引擎 → 列车/进路复位 → 同步 B站轨道 → 重算码序/信号 → 仿真时钟归零 → 刷新进路控件与整图”的顺序执行。

- [ ] **Step 6: 写纯文本视觉合同测试**

扩展 `test_train_status_area_uses_plain_route_and_state_labels`：三项仍为 `QLabel`、自身 `styleSheet()` 为空且 `autoFillBackground()` 为假；`APP_STYLESHEET` 中不再存在 `QLabel#train_route_value, QLabel#train_state_value` 专用框式规则；同时在 1600×760 下各文本边界不与相邻控件重叠。

- [ ] **Step 7: 移除输入框式视觉样式**

在 `ui/theme.py` 删除 `QLabel#train_route_value, QLabel#train_state_value` 的边框、背景、圆角和内边距规则；在 `ui/main_window.py` 调整三个值标签的最小宽度和布局 stretch，使其表现与第二、三行普通信息一致。

- [ ] **Step 8: 运行 Task 4 专项与全量测试**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch tests.test_phase1_ui -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 9: 更新进度并提交上传**

```bash
git add models/train.py services/train_service.py ui/main_window.py ui/theme.py tests/test_multi_train_dispatch.py tests/test_phase1_ui.py PROGRESS.md
git commit -m "fix: clear routes and train modes on reset"
git push origin main
```

### Task 5: 四组合联调、视觉验收与恢复文档

**Files:**
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `tests/test_phase1_ui.py`
- Create: `docs/phases/PHASE-06-STATION-PATH-SIGNAL-RESET.md`
- Create: `docs/images/phase-06-station-path-signal-reset-1600x760.png`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Tasks 1–4 的全部公开接口与状态快照
- Produces: A→B/B→A × 正线/侧线的端到端回归、1600×760 验收图和断线可恢复说明

- [ ] **Step 1: 写四种接发组合端到端测试**

增加 `test_all_direction_and_track_combinations_depart_from_station_path_and_arrive`：逐项覆盖 A→B/B→A × MAIN/SIDE，验证待发 x1、DEPARTING、不提前占用入口、进入 G01/G38、目标站外等待、接车后沿对应路径运行、进路释放及最终 ARRIVED。

- [ ] **Step 2: 写多车与信号联合回归测试**

增加 `test_multiple_trains_update_codes_signals_and_waiting_count_together`：两辆运行车加两辆待发车时断言 x2 单一标记、每辆每 tick 只推进一次、占用变化触发码序和所防护信号变化、复位后 x4 且所有信号按无进路状态关闭。

- [ ] **Step 3: 运行端到端测试**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch tests.test_route_integration tests.test_phase1_ui -v`

Expected: PASS。

- [ ] **Step 4: 运行全量与静态验证**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

Run: `.venv/bin/python -m compileall models services ui tests`

Expected: 成功，退出码 0。

Run: `git diff --check`

Expected: 无输出，退出码 0。

- [ ] **Step 5: 生成 1600×760 离屏验收图**

复用 `tests/test_phase1_ui.py` 的 Qt offscreen 启动方式，构造“两辆待发、一辆侧线 DEPARTING、一辆区间运行、动态码序和有效临时限速”状态，保存为 `docs/images/phase-06-station-path-signal-reset-1600x760.png`。

- [ ] **Step 6: 检查验收图**

使用图像查看工具确认：仅一个 x2 待发标记、侧线车落在斜坡或 3G、信号灯与码序一致、三项只读状态无框、1:4:5 板块和所有文字在 1600×760 下无覆盖。

- [ ] **Step 7: 写阶段恢复文档**

在 `docs/phases/PHASE-06-STATION-PATH-SIGNAL-RESET.md` 记录实现范围、关键接口、状态机、信号映射、验证命令及结果、验收图路径、已知限制和下次恢复入口。

- [ ] **Step 8: 更新总进度文档**

在 `PROGRESS.md` 将本阶段标记完成，记录全量测试数量、最终提交、截图和下一阶段入口。

- [ ] **Step 9: 提交并上传最终验收**

```bash
git add tests/test_multi_train_dispatch.py tests/test_phase1_ui.py docs/phases/PHASE-06-STATION-PATH-SIGNAL-RESET.md docs/images/phase-06-station-path-signal-reset-1600x760.png PROGRESS.md
git commit -m "test: verify station paths signals and full reset"
git push origin main
```
