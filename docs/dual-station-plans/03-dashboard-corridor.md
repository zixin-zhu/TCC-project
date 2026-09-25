# 阶段 3：双站总览、快照聚合与联合站场图 Implementation Plan（实施方案）

> **给执行 Codex：** 使用 `superpowers:executing-plans`、PyQt Widgets/Core/Styling；测试先行，聚合器保持纯只读。

**目标：** 建成单窗口经典控制台：首页同时显示 A/B 关键状态和配置驱动的统一线路图，所有信息来自两站快照。

**架构：** 纯 Python 聚合器计算双站视图模型；Qt 摘要卡和线路图只渲染模型；主窗口用左侧导航和 `QStackedWidget` 组织页面。

**技术栈：** Python 3.12、PyQt5 QPainter/QStackedWidget、pytest/pytest-qt。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束与复审重点

- A 是方向权威；B 方向只做一致性比较。
- 共享区段不一致必须可见并触发总览锁闭，不能静默选边。
- 站场对象严格来自 `topology.json`，不得照抄参考图四股道/S1～S8。
- 颜色旁必须有文字；黑白截图仍能辨认状态。
- 1280×800 不遮挡关键状态，1920×1080 不出现大片无效空白。

## 任务 1：实现不可变双站视图模型

**文件：** 新建 `app/ui/dual_snapshot.py`；测试 `tests/unit/test_dual_snapshot.py`。

**接口：**

```python
@dataclass(frozen=True)
class SectionConsistency:
    section_id: str
    station_a_state: TrackState
    station_b_state: TrackState
    consistent: bool
    display_state: TrackState | None
    reason: str

@dataclass(frozen=True)
class DualStationSnapshot:
    station_a: TccSnapshot
    station_b: TccSnapshot
    authoritative_direction: RunningDirection
    direction_consistent: bool
    communication_healthy: bool
    operation_locked: bool
    sections: tuple[SectionConsistency, ...]
    active_alarm_count: int
    critical_alarm_count: int

class DualStationSnapshotAggregator(QObject):
    snapshot_changed = pyqtSignal(object)
    def update_a(self, snapshot: TccSnapshot) -> None: ...
    def update_b(self, snapshot: TccSnapshot) -> None: ...
```

- [ ] 测试 A/B 任意顺序更新、重复快照、方向不一致、通信降级、锁闭、告警求和、共享区段不一致。
- [ ] 在收到两站首份快照前不发完整模型；不得拼出 `None` 站点。
- [ ] 实现站内区段来源规则和 Q1～Q4 双值比较，不修改控制器。

## 任务 2：实现摘要卡和全局状态条

**文件：** 新建 `app/ui/station_summary_card.py`、`app/ui/global_status_bar.py`；测试 `tests/integration/test_dual_dashboard.py`。

- [ ] 测试每张卡显示站名、角色、通信、版本、方向、锁闭、进路、边界状态/码序、主信号、LEU 模式、限速数、告警数、收发计数。
- [ ] 实现 `navigate_requested = pyqtSignal(str)`，按钮只导航，不改业务状态。
- [ ] 状态图标同时显示中文；使用语义动态属性刷新 QSS。

## 任务 3：实现配置驱动联合线路图

**文件：** 新建 `app/ui/corridor_overview_widget.py`；测试 `tests/integration/test_corridor_widget.py`。

- [ ] 用测试配置增加/减少区段，证明绘制顺序和宽度来自配置而非固定 Q1～Q4。
- [ ] `paintEvent` 绘制区段 ID/名称/状态/码序/长度、信号、应答器、方向箭头、锁闭横条。
- [ ] 不一致区段使用黄黑视觉并绘制“不一致”；空闲/占用/故障/分路不良使用设计基线颜色。
- [ ] 暴露 `set_snapshot(DualStationSnapshot)` 和只读 hit-test，用于点击区段后导航到相应详情，不在图元内直接改状态。

## 任务 4：组装经典控制台主窗口

**文件：** 新建 `app/ui/dual_main_window.py`；修改 `run_dual.py`；测试 `tests/integration/test_dual_main_window.py`。

- [ ] 左侧导航严格包含设计基线 12 个真实入口，并与 `QStackedWidget` 一一对应。
- [ ] 首页按“标题/全局状态—A/B 摘要卡—统一线路图—最近事件/严重告警”布局。
- [ ] A站控制/B站控制嵌入阶段 2 的 `StationDetailWidget`；其他详情页本阶段可复用其对应子页，但不得出现空白占位页。
- [ ] 连接聚合快照刷新；UI 不轮询控制器，不复制领域规则。
- [ ] `run_dual.py` 创建正式窗口并把关闭委托给 `DualStationApplication`。

## 任务 5：验收与提交

- [ ] pytest-qt 检查所有导航、字段、状态颜色属性和窗口关闭。
- [ ] 在 1280×800、1440×900、1920×1080 生成截图并目视对照方案一。
- [ ] 全量测试、真实双站握手、compileall、diff check；独立复审。
- [ ] 更新防中断文档并提交：

```bash
git add app/ui run_dual.py tests docs/IMPLEMENTATION_STATUS.md
git commit -m "feat: add classic dual-station control dashboard"
git push origin codex/dual-station-dashboard
```

## 验收门

一个窗口同时显示两站关键数据；联合线路图配置驱动；不一致不被掩盖；12 个导航均有真实内容；视觉与方案一一致。

## Codex 执行提示词

```text
执行双站同屏阶段 3。读设计基线、本文件和阶段 2 组件。先实现纯只读 DualStationSnapshotAggregator 并覆盖快照顺序、锁闭、告警和不一致测试，再做摘要卡、全局状态条和 CorridorOverviewWidget。界面严格采用参考图方案一的浅色经典控制台，但设备、信号和按钮必须来自本项目配置与真实功能，禁止照抄示意对象。用左导航+QStackedWidget 组装唯一主窗口，验证三种分辨率、真实双站和全量回归，复审后提交推送。
```
