# 阶段 4：双站操作、改方网络与联合列车演示 Implementation Plan（实施方案）

> **给执行 Codex：** 使用 `superpowers:executing-plans`、TDD、PyQt Core/Widgets；所有写操作必须经过控制器。

**目标：** 让经典控制台中的所有按钮对应真实业务能力，并建立一份跨 A/B 的列车演示状态，完整支持正反向运行和安全降级。

**架构：** UI 通过明确的目标站路由命令；方向改方始终由 A 发起；`SharedTrackInputAdapter` 模拟同一物理轨道输入送达两站；`DualTrainCoordinator` 负责唯一列车状态和定时推进。

**技术栈：** Python 3.12、PyQt5、现有 `TccController`、pytest/pytest-qt。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束与复审重点

- UI 不直接修改 runtime 字段，只调用 `TccController` 公共命令。
- Q1～Q4 的同源轨道输入要分别通过 A/B 控制器，不能复制内部状态。
- 双写部分成功时保持占用并报警，禁止回滚成“空闲”。
- 改方按钮只调用 A；B 页面只能显示投影和拒绝原因。
- 复位只清 TRAIN 来源，不清人工、故障或分路不良。

## 任务 1：共享轨道输入适配器

**文件：** 新建 `app/services/shared_track_input.py`；测试 `tests/unit/test_shared_track_input.py`。

**接口：**

```python
@dataclass(frozen=True)
class DualWriteResult:
    success: bool
    reason: str
    station_a: OperationResult | None
    station_b: OperationResult | None

class SharedTrackInputAdapter:
    def set_state(
        self, section_id: str, source: TrackInputSource, state: TrackState
    ) -> DualWriteResult: ...
```

- [ ] 测试 A_T* 仅写 A、B_T* 仅写 B、Q* 按 A 后 B 写两站、未知 ID 两站均不写。
- [ ] 测试 A 成功 B 失败时返回失败，A 占用保持且产生 `SHARED_INPUT_PARTIAL_FAILURE` 严重告警；禁止清回空闲。
- [ ] source 只允许 TRAIN；人工单站操作仍走目标站控制器。
- [ ] 实现并运行：`.venv/bin/python -m pytest tests/unit/test_shared_track_input.py -q`。

## 任务 2：联合列车协调器

**文件：** 新建 `app/services/dual_train_coordinator.py`；测试 `tests/unit/test_dual_train_coordinator.py`。

**接口：**

```python
class DualTrainCoordinator(QObject):
    trains_changed = pyqtSignal(object)
    operation_failed = pyqtSignal(str)
    def create_train(self) -> TrainDemoState: ...
    def dispatch(self, train_id: str) -> OperationResult: ...
    def start(self) -> OperationResult: ...
    def pause(self, reason: str = "人工暂停") -> None: ...
    def reset(self) -> OperationResult: ...
    def tick(self, elapsed_s: float) -> None: ...
```

- [ ] 测试 A→B/B→A 顺序、发车进路门禁、前方占用停车、到达、方向锁闭和通信降级暂停。
- [ ] 测试转换顺序为“下一段占用成功→上一段清除”；部分失败不丢列车占用。
- [ ] 使用一个 500 ms 父属 QTimer；窗口关闭前停止，禁止每站各建列车 timer。
- [ ] 输出列车 ID、方向、区段、位置、当前/目标速度、前方距离、最后应答器、安全状态。

## 任务 3：实现真实快捷操作与详情页

**文件：** 修改 `app/ui/dual_main_window.py`；新建 `app/ui/dual_operations_pages.py`；测试 `tests/integration/test_dual_operations.py`。

- [ ] 轨道页先选 A/B/共享目标、区段和状态；共享目标仅允许 Q1～Q4。
- [ ] 信号页选择站点和信号，调用目标控制器灯丝故障命令。
- [ ] LEU 页左右显示端口、模板、模式和原因；HEX/位流放子标签。
- [ ] 限速页明确目标站，支持预存/执行/撤销并同时显示 A/B 列表。
- [ ] 改方/网络页只启用 A 申请按钮，显示事务阶段、锁闭、方向一致性、收发计数。
- [ ] 快捷按钮包含动作与对象，不增加无实现的连接、设置或帮助按钮。
- [ ] 结果栏显示目标站、成功/拒绝、原因和状态版本。

## 任务 4：迁移既有七场景

**文件：** 修改 `app/services/demo_scenarios.py`、`docs/DELIVERY_SCENARIOS.md`；测试 `tests/unit/test_demo_scenarios.py`。

- [ ] 为七场景增加 `target_page`、`target_station`、`preconditions`、`reset_steps`，ID 不变。
- [ ] 全部步骤改为 `run_dual.py` 单窗口操作，保留异常预期和复位。
- [ ] 测试每个场景引用的导航页和按钮对象名真实存在。

## 任务 5：验证、复审与提交

- [ ] 运行联合操作、列车、窗口、网络、改方测试和全量 pytest。
- [ ] 人工执行正反向列车、正常改方、断线锁闭和部分失败注入。
- [ ] 更新防中断文档；独立复审无 Critical/Important 后提交：

```bash
git add app/services app/ui tests docs
git commit -m "feat: integrate dual-station operations and train demo"
git push origin codex/dual-station-dashboard
```

## 验收门

所有按钮均有真实功能；联合列车状态唯一；同源轨道输入安全双写；断线、改方和不一致均停车锁闭；七场景可在单窗口完成。

## Codex 执行提示词

```text
执行双站同屏阶段 4。读设计基线、本文件、TccController、TrainDemoService 和七场景文档。先测试 SharedTrackInputAdapter：站内只写所属站，共享 Q 区段把同一外部检测输入分别送入 A/B 控制器，部分失败保持保守占用并报警。再实现唯一 DualTrainCoordinator 和真实操作页；改方只能由 A 发起，所有 UI 写操作经过控制器。禁止空按钮、内部状态直写和复位清除人工/故障来源。完成七场景迁移、全量回归、人工故障演练和独立复审后提交推送。
```
