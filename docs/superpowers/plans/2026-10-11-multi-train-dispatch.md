# TCC Multi-Train Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现“只发当前选中列车”的多列车并行仿真、全局暂停/继续与复位、每车实时最大速度，以及基于全部列车占用的编码和信号联动。

**Architecture:** `Train` 保存每车配置和可展示状态，`TrainService` 负责明确列车编号的立即发车及多车推进，`SimulationService` 继续以统一占用集合生成编码和信号，`MainWindow` 只围绕当前选中列车协调控件与完整错误提示。删除单一延迟目标的业务依赖，所有状态变更都通过一次同步占用后统一刷新。

**Tech Stack:** Python 3、PyQt5、`unittest`、现有领域模型与服务层。

**Spec:** `docs/superpowers/specs/2026-10-11-multi-train-dispatch-design.md`

## Global Constraints

- 区间固定为 38 个轨道区段、每两个区段组成一个闭塞分区，共 19 个闭塞分区。
- “发车”一次只处理“查看列车”当前选中的一辆待发列车，不建立隐式自动等待目标。
- 最大速度固定选项为 `80、120、160、200、250、300、350 km/h`，默认 `120 km/h`。
- 进路只能人工取消；列车通过、复位或清车只解除锁闭，不删除进路。
- 不新增日志功能，不改变站场物理设备位置、进路类型和临时限速范围规则。
- 每个任务执行 RED→GREEN→REFACTOR，更新 `PROGRESS.md`，普通提交并推送，禁止强制推送。

## Review Focus

- 暂停期间选中或添加待发列车不得改变已经发车列车，Task 2 和 Task 4 必须覆盖。
- 两车恰处于相邻区段或同一周期跨越边界时不得重叠、超越，Task 3 必须覆盖。
- 运行中降低最大速度应通过目标速度和制动过程生效，不能瞬间改当前速度，Task 1 和 Task 3 必须覆盖。
- 复位必须同时处理运行、停车和已到达列车，同时保持从未发车列车、进路和临时限速，Task 2 和 Task 4 必须覆盖。
- 切换列车时信号阻塞不得把程序性控件刷新误当成人工编辑，Task 4 必须覆盖。

---

### Task 1: 每车最大速度与状态模型

**Files:**
- Modify: `models/train.py`
- Create: `tests/test_multi_train_dispatch.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: 现有 `Train.configure_operation_modes()`、`Train.calculate_target_speed()` 和 `Train.get_status()`。
- Produces: `Train.ALLOWED_MAX_SPEEDS: tuple[int, ...]`、`Train.set_max_speed(speed: float) -> None`、`Train.reset_to_departure(preserve_configuration: bool = True) -> None`，状态快照字段 `max_speed`。

- [ ] **Step 1: 写最大速度和复位语义的失败测试**

在 `MultiTrainModelTest` 中新增：

```python
def test_train_max_speed_options_and_status_snapshot(self):
    train = Train("T001")
    self.assertEqual(train.ALLOWED_MAX_SPEEDS, (80, 120, 160, 200, 250, 300, 350))
    train.set_max_speed(250)
    self.assertEqual(train.get_status()["max_speed"], 250.0)

def test_reset_preserves_configuration_and_unlocks_editing(self):
    train = Train("T001", "A_TO_B", "SIDE", "MAIN")
    train.set_max_speed(200)
    train.enter_track("G01")
    train.reset_to_departure()
    self.assertEqual((train.departure_mode, train.arrival_mode), ("SIDE", "MAIN"))
    self.assertEqual(train.max_speed, 200.0)
    self.assertEqual(train.status, "WAITING")
```

同时验证 `set_max_speed(100)` 抛出包含允许值的 `ValueError`，以及降低最大速度只降低 `target_speed`、不直接修改 `speed`。

- [ ] **Step 2: 运行测试确认因接口缺失而失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainModelTest -v`

Expected: FAIL，指出 `ALLOWED_MAX_SPEEDS` 或 `set_max_speed` 不存在。

- [ ] **Step 3: 实现最小模型改动**

在 `models/train.py` 实现上述接口；`calculate_target_speed()` 继续取所有约束最小值；`reset_to_departure()` 默认保留接发方式和最大速度，只清理运行位置、动态约束、应答器和安全状态。

- [ ] **Step 4: 运行模型测试和全量回归**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainModelTest -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS；若既有测试仍断言复位清空接发方式，只把该断言改为已确认的新语义。

- [ ] **Step 5: 更新进度并提交、推送**

```bash
git add models/train.py tests/test_multi_train_dispatch.py PROGRESS.md
git commit -m "feat: add per-train maximum speed state"
git push origin main
```

### Task 2: 明确单车发车与全局生命周期

**Files:**
- Modify: `services/train_service.py`
- Modify: `services/simulation_engine.py`
- Modify: `services/operation_policy.py`
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 的 `Train.set_max_speed()` 和保留配置复位语义；现有 `OperationRuleError`。
- Produces: `TrainService.dispatch_selected_train(train_id: str, departure_mode: str, arrival_mode: str, max_speed: float) -> Train`、`pause_all() -> list[Train]`、`resume_all() -> list[Train]`、`reset_dispatched_trains() -> list[Train]`、`get_dispatch_blocker(train: Train) -> OperationRuleError | None`；`SimulationEngine.is_paused: bool`。

- [ ] **Step 1: 写“只发选中列车”和失败原子性的测试**

建立 A→B 正线发车/接车进路，添加 T001、T002，调用 `dispatch_selected_train("T002", "MAIN", "MAIN", 200)`，断言只有 T002 为 `RUNNING`、T001 仍在待发队列；缺进路、入口占用或前车未到 G03 时抛出三段式 `OperationRuleError`，且列车、队列、进路锁闭和占用均不变。

- [ ] **Step 2: 写全局暂停/继续/复位失败测试**

构造 `RUNNING`、`STOPPED`、`ARRIVED` 和从未发车 `WAITING` 列车，验证：

- `pause_all()` 只把运行列车转为停车；
- `resume_all()` 恢复可运行列车；
- `reset_dispatched_trains()` 将前三类送回出发点、保留配置并回到待发队列；
- 从未发车列车保持原配置和顺序；
- 进路仅解除锁闭，不被删除。

- [ ] **Step 3: 运行测试确认旧延迟发车机制不符合要求**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainLifecycleTest -v`

Expected: FAIL，指出新接口不存在或 T002 未被立即单独发出。

- [ ] **Step 4: 实现明确发车和全局状态接口**

移除 `prepare_train_for_dispatch()`、`try_auto_dispatch()` 和 `dispatch_target_id` 对正常流程的依赖。`dispatch_selected_train()` 必须先完成全部只读校验，再一次性写入配置、锁闭进路、进入入口区段并移出待发队列；错误通过 `OperationRuleError` 返回具体列车、区段或前车信息。

`SimulationEngine` 记录用户暂停状态，`start()`/`pause()` 不再替代列车服务的状态转换；继续操作显式调用 `resume_all()`。

- [ ] **Step 5: 运行任务测试和全量回归**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainLifecycleTest -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS，既有“自动发车目标”测试改为“明确选中立即发车”。

- [ ] **Step 6: 更新进度并提交、推送**

```bash
git add services/train_service.py services/simulation_engine.py services/operation_policy.py tests/test_multi_train_dispatch.py tests PROGRESS.md
git commit -m "feat: dispatch one selected train explicitly"
git push origin main
```

### Task 3: 多车同步推进、追踪防护与编码信号

**Files:**
- Modify: `services/train_service.py`
- Modify: `services/simulation_service.py`
- Modify: `tests/test_multi_train_dispatch.py`
- Modify: `tests/test_route_integration.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 2 的明确发车和全局生命周期接口；现有 `find_train_ahead()`、`get_safety_status()`、`calculate_train_block_code()`。
- Produces: `build_movement_snapshot() -> dict[str, dict]`、`update_all(delta_time: float) -> None` 的同步多车语义，以及多占用点取更严格编码的稳定行为。

- [ ] **Step 1: 写多车互斥、追踪和速度约束失败测试**

覆盖：

- 两辆同向列车同时运行且每周期都有位置变化；
- 前车在 G03 后车才可发出，G01/G02 时错误提示含前车编号、区段和处理建议；
- 两车相邻区段跨界时后车停在边界前，不进入前车区段、不超越；
- 运行中把后车最大速度从 250 改为 80 后，`target_speed <= 80` 且当前速度按 `deceleration` 逐步降低；
- 暂停期间 `update_all()` 不改变停车列车位置。

- [ ] **Step 2: 写多占用点编码和入口信号失败测试**

人工占用 G03、G08 后调用统一同步，断言每个占用点后方码序均生成防护，重叠防护采用速度更低的码；入口间隔不足时发车信号为红，前车到 G03 且进路可用后恢复允许显示。

- [ ] **Step 3: 运行测试确认当前顺序更新存在失败**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainMovementTest tests.test_route_integration -v`

Expected: FAIL，至少显示相邻跨界、最大速度实时更新或多占用点编码断言不满足。

- [ ] **Step 4: 实现移动快照与保守提交**

移动前冻结本周期所有活动列车的区段、区段内位置和绝对位置；按运行方向从前到后计算移动意图，使用已保留的目标区段集合阻止重叠；全部意图确定后再提交位置，最后只调用一次 `sync_track_circuits()` 和编码/信号更新。

保持现有 38 区段码序表；多个防护源影响同一区段时按 `BLOCK_SPEED_LIMITS` 选择速度更低的码。最大速度仅进入目标速度最小值，不直接修改当前速度。

- [ ] **Step 5: 运行任务测试和全量回归**

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch.MultiTrainMovementTest tests.test_route_integration -v`

Expected: PASS。

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 6: 更新进度并提交、推送**

```bash
git add services/train_service.py services/simulation_service.py tests/test_multi_train_dispatch.py tests/test_route_integration.py PROGRESS.md
git commit -m "feat: protect multi-train interval movement"
git push origin main
```

### Task 4: 当前列车 UI、最大速度和全局控制

**Files:**
- Modify: `ui/main_window.py`
- Modify: `ui/theme.py`
- Modify: `tests/test_phase1_ui.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: Task 1 的最大速度接口、Task 2 的明确发车和全局生命周期接口、Task 3 的实时状态。
- Produces: `dispatch_selected_train() -> None`、`toggle_pause_simulation() -> None`、`change_selected_train_max_speed(text: str) -> None`、`sync_selected_train_controls() -> None`，以及 `MAX_SPEED_LABELS` 固定选项。

- [ ] **Step 1: 写 UI 结构和选中列车同步失败测试**

断言：

- 开始按钮文字为“▶ 发车”；
- 接车方式右侧存在“最大速度：”和七个固定选项，默认 `120 km/h`；
- 选中 T001/T002 时展示各自状态和最大速度；
- `RUNNING`/`STOPPED`/`ARRIVED` 时接发方式禁用，待发时启用；
- 运行和停车列车的最大速度可编辑，到达列车禁用；
- 程序刷新控件时使用信号阻塞，不误写另一列车配置。

- [ ] **Step 2: 写单车发车、全局暂停/继续/复位和错误弹窗失败测试**

使用 `QMessageBox.warning` 验证：

- 点击发车只改变当前选中待发列车；
- 发车成功后时钟启动，另一个待发列车不变；
- “Ⅱ 暂停”停止全部运行列车并变为“▶ 继续”，再次点击全部继续；
- 复位全部已发车列车，但保留未发车列车、进路和临时限速；
- 无选择、已发车重复点击、缺进路、入口占用、前车间隔不足、无运行车暂停、无已发车车复位均显示“操作失败/当前状态/处理建议”。

- [ ] **Step 3: 运行 UI 测试确认失败原因正确**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui.PhaseOneUiContractTest -v`

Expected: FAIL，指出按钮文字、最大速度控件或全局控制语义不符合要求。

- [ ] **Step 4: 实现紧凑 UI 与事件协调**

在现有单行选择区中把最大速度标签和选择框放在接车方式右侧，采用与相邻选择框一致的高度和可读宽度；不改变区间改方、进路建立、临时限速的 `1:4:5` 布局。

将原 `start_simulation()` 替换为当前列车明确发车处理；暂停按钮改为切换处理；复位调用全局复位接口。`train_selector.currentTextChanged` 同步当前列车信息和控件，程序性设置组合框时阻塞信号。

- [ ] **Step 5: 运行 UI 测试和全量回归**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_phase1_ui.PhaseOneUiContractTest -v`

Expected: PASS。

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS。

- [ ] **Step 6: 更新进度并提交、推送**

```bash
git add ui/main_window.py ui/theme.py tests/test_phase1_ui.py PROGRESS.md
git commit -m "feat: add selected-train dispatch controls"
git push origin main
```

### Task 5: 集成验收、视觉检查与恢复文档

**Files:**
- Create: `docs/phases/PHASE-05.md`
- Modify: `docs/TCC功能仿真实现方案.md`
- Modify: `PROGRESS.md`
- Create: `docs/images/phase-05-multi-train-1600x760.png`

**Interfaces:**
- Consumes: Task 1～4 的完整功能。
- Produces: 可恢复的阶段记录、最终验收证据和与实现一致的总方案。

- [ ] **Step 1: 运行多车端到端场景**

建立正确接发进路，依次添加并发出至少两辆列车，验证当前列车切换、前车间隔拒绝与恢复、运行中最大速度降低、全局暂停/继续、全局复位、编码和信号变化。

Run: `.venv/bin/python -m unittest tests.test_multi_train_dispatch -v`

Expected: PASS。

- [ ] **Step 2: 运行全部自动检查**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v`

Expected: 全部 PASS，无异常和资源警告。

Run: `.venv/bin/python -m compileall -q models services ui tests`

Expected: exit 0。

Run: `git diff --check`

Expected: 无输出。

- [ ] **Step 3: 截图检查 1600×760 布局**

使用现有离屏截图方式生成 `docs/images/phase-05-multi-train-1600x760.png`，检查新增最大速度控件不遮挡，按钮文字完整，下拉框宽度合理，原 `1:4:5` 操作区不变。

- [ ] **Step 4: 更新阶段和恢复文档**

`docs/phases/PHASE-05.md` 记录实现语义、错误提示和验证命令；总方案同步单车选择发车、多车追踪和最大速度；`PROGRESS.md` 写入最终提交、测试数和下一恢复入口。

- [ ] **Step 5: 提交并普通推送**

```bash
git add docs/phases/PHASE-05.md docs/TCC功能仿真实现方案.md docs/images/phase-05-multi-train-1600x760.png PROGRESS.md
git commit -m "docs: complete multi-train simulation phase"
git push origin main
```

