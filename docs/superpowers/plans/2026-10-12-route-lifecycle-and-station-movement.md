# TCC Route Lifecycle and Station Movement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现只依赖发车进路的发车、最前方列车接车进路分配、进路通过后自动删除、目标站内连续运行，以及对应的三行状态栏与2D列车显示。

**Architecture:** 在 `Train` 中增加独立于暂停状态的运行阶段和发车/接车进路绑定；`TrainService` 负责按方向位置分配接车进路，并推进区间与站内两个坐标域；`MainWindow` 只读展示由实际进路派生的接发方式；`TccOverviewWidget` 使用同一站场几何合同绘制精确白光带和待发、区间、站内列车。

**Tech Stack:** Python 3、PyQt5、`unittest`、现有模型/服务/自绘站场组件。

**Spec:** `docs/superpowers/specs/2026-10-12-route-lifecycle-and-station-movement-design.md`

## Global Constraints

- 区间固定38个区段、19个闭塞分区，区段编号与现有几何不变。
- 发车不依赖接车进路；接车进路只分配给最靠近目标站的未分配列车。
- A→B越过目标站X1/X3、B→A越过目标站S1/S3后删除接车进路。
- 列车越过目标站另一端外方信号机后才完成运行。
- UI保持紧凑、美观，状态栏为指定三行布局；不新增日志功能。
- 每项采用 RED→GREEN→REFACTOR，更新 `PROGRESS.md`，普通提交并推送，禁止强制推送。

## Review Focus

- 全局暂停造成的 `STOPPED` 与缺少接车进路造成的等待必须可区分，防止无进路自动恢复；Task 2覆盖。
- 多车接近终点时，新接车进路只能分配给最前车，后车不得借用；Task 1和Task 2覆盖。
- 发车进路删除后第二辆车必须重新建立新进路，即使入口间隔已经满足；Task 1覆盖。
- 接车进路删除点必须是目标站X1/X3或S1/S3，不得在进入最后区间或刚越过进站信号机时删除；Task 2覆盖。
- 复位或清车时不存在的自动释放进路不能被意外恢复，锁闭引用不得悬空；Task 1和Task 4覆盖。

---

### Task 1: 运行阶段、实际进路派生和自动释放

**Files:**
- Modify: `models/train.py`
- Modify: `services/operation_policy.py`
- Modify: `services/route_service.py`
- Modify: `services/train_service.py`
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `Train.movement_phase`、`departure_route_id`、`receive_route_id`、`receive_waiting_reason`；`TrainService.assign_receive_route(route) -> Train | None`；只校验实际发车进路的 `dispatch_selected_train(train_id, max_speed) -> Train`。
- Consumes: 现有 `RouteService.departure_route_for()`、`receive_route_for()`、`lock_route()`、`release_route()` 和区间前后车间隔判断。

- [ ] **Step 1: 写发车只依赖发车进路、方式由进路派生和发车进路自动删除的失败测试**

覆盖正/侧线与两个方向；无接车进路也可发车；进入G01/G38后发车进路从 `active_routes()` 消失；第二辆车必须重新建立发车进路。

- [ ] **Step 2: 运行专项测试确认旧的双进路校验失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainLifecycleTest tests.test_route_integration.RouteTrainIntegrationTest -v`

Expected: FAIL，显示缺少接车进路仍拒绝发车或进路只解锁未删除。

- [ ] **Step 3: 最小实现运行阶段和分离的进路绑定**

`Train` 分别保存发车和接车进路编号与派生方式；发车校验只读取当前方向出发站唯一发车进路；进入区间即调用 `release_route()` 删除发车进路并清理列车绑定。

- [ ] **Step 4: 写并实现“接车进路分配给最前车”的失败测试**

以两个同向活动列车构造不同累计位置，建立接车进路后调用分配接口，断言只锁闭给靠近目标站者；释放后新进路才能分配给后车；无候选列车返回空且不锁闭。

- [ ] **Step 5: 运行专项和全量测试**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch tests.test_route_integration -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部PASS。

- [ ] **Step 6: 更新进度，提交并推送**

Commit: `feat: separate departure and receive route lifecycle`

### Task 2: 目标站外等待、站内运行与精确释放点

**Files:**
- Modify: `models/train.py`
- Modify: `services/train_service.py`
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 的 `movement_phase`、独立进路绑定和最前车分配。
- Produces: 区间末端等待语义；`station_position` 与 `station_track`；区间、接车、股道、出站连续推进；接车进路精确自动删除。

- [ ] **Step 1: 写无接车进路时停在最后区间且不能自动恢复的失败测试**

分别覆盖A→B的G38和B→A的G01；调用多次 `update_all()` 仍不得进入站内；建立匹配接车进路后仅最前车恢复。

- [ ] **Step 2: 写站内连续运行和接车进路释放点失败测试**

覆盖A→B正/侧线越过B站X1/X3释放，B→A正/侧线越过A站S1/S3释放；释放后继续运行，越过B站S或A站X后才为 `ARRIVED`。

- [ ] **Step 3: 运行测试确认当前最后区段直接到达的逻辑失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainStationMovementTest tests.test_route_integration.RouteTrainIntegrationTest -v`

Expected: FAIL，显示列车在最后区段后直接 `ARRIVED` 或无进路仍离开区间。

- [ ] **Step 4: 实现区间末端门控和站内坐标推进**

等待接车进路使用独立阶段/原因；`try_resume_stopped_trains()` 只在进路已分配且非全局暂停时恢复。站内进度按接车进路、股道和驶出三段推进，并在确认信号边界后删除接车进路。

- [ ] **Step 5: 运行专项和全量测试**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainStationMovementTest tests.test_route_integration -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部PASS。

- [ ] **Step 6: 更新进度，提交并推送**

Commit: `feat: continue trains through destination stations`

### Task 3: 三行状态栏、精确白光带和全线路列车绘制

**Files:**
- Modify: `ui/main_window.py`
- Modify: `ui/tcc_overview.py`
- Modify: `ui/theme.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `tests/test_review_corrections.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1/2 状态快照中的派生接发方式、运行阶段、站内位置和进路绑定。
- Produces: 只读 `departure_mode_value`、`arrival_mode_value`、`train_state_value`；指定三行四列状态网格；方向/类型精确白光带；待发及站内列车绘制合同。

- [ ] **Step 1: 写UI结构与只读显示失败测试**

断言接发方式为 `QLabel` 而非 `QComboBox`；第一行包含查看列车、发车方式、接车方式、当前列车状态、最大速度；状态网格严格三行四列且不存在分区位置和目标速度。

- [ ] **Step 2: 写进路白光带和列车位置合同失败测试**

断言四种方向/进路组合返回精确起止信号；待发列车A→B位于A站X右侧、B→A位于B站S左侧并依次标记x1/x2；站内列车坐标随 `station_position` 单调移动。

- [ ] **Step 3: 运行UI专项测试确认旧下拉框与粗粒度路径失败**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui tests.test_review_corrections -v`

Expected: FAIL，显示接发方式仍为下拉框、网格仍为两行五列或白光带端点不精确。

- [ ] **Step 4: 实现响应式三行布局与全线路绘制**

使用布局伸缩比例而非固定坐标排列状态栏；最大速度仍可操作。绘图层从站场几何合同读取信号坐标，按运行阶段绘制待发、区间、等待接车、接车、站内和驶出列车。

- [ ] **Step 5: 运行UI专项、截图检查和全量测试**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui tests.test_review_corrections -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部PASS。

- [ ] **Step 6: 更新进度，提交并推送**

Commit: `feat: show route-derived train state and station movement`

### Task 4: 集成验收与恢复文档

**Files:**
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `tests/test_phase1_ui.py`
- Create: `docs/phases/PHASE-05-ROUTE-LIFECYCLE.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: 前三项全部行为。
- Produces: A→B、B→A、多车等待与重新建立进路的端到端回归，以及可从中断处继续的恢复说明。

- [x] **Step 1: 添加两方向端到端测试**

验证两车依次发车、发车进路重建、前车独占接车进路、后车在站外等待、前车驶出、后车重新接车的完整流程。

- [x] **Step 2: 运行全量验证与静态检查**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部PASS。

Run: `.venv/bin/python -m compileall models services ui tests`

Expected: exit 0。

Run: `git diff --check`

Expected: 无输出，exit 0。

- [x] **Step 3: 使用离屏截图检查最小窗口布局**

在1600×760下检查三行状态栏、最大速度、三操作板块和2D站场无文字遮挡、无控件裁切、无明显无效留白。

- [x] **Step 4: 写恢复文档并更新进度**

记录新状态机、进路释放时机、接车分配规则、测试数量、截图路径和下一恢复入口。

- [x] **Step 5: 最终提交并推送**

Commit: `docs: complete route lifecycle and station movement revision`
