# 阶段 2：单站 UI 组件化与经典控制台主题 Implementation Plan（实施方案）

> **给执行 Codex：** 使用 `superpowers:executing-plans` 和 PyQt Widgets/Core/Styling 技能；先测试后重构，禁止改变业务规则。

**目标：** 把现有单站 `TccMainWindow` 拆成可嵌入组件，并建立与参考图方案一一致的经典浅色控制台主题，同时保持单站功能完全兼容。

**架构：** `StationDetailWidget` 只持控制器并展示/发送命令；`TccMainWindow` 变成兼容壳并拥有单站生命周期；主题集中管理，不在控件里散落 QSS。

**技术栈：** Python 3.12、PyQt5 QtWidgets/QSS、pytest-qt。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束与复审重点

- 不改 `TccController`、编码、点灯、LEU、改方规则。
- 原九页按钮、字段和交互全部保留；不得出现空按钮。
- 只使用布局和 size policy，不使用固定坐标。
- 经典主题是浅灰白工业控制台，不得变成深色卡片风。
- 单站窗口关闭失败时仍拒绝退出，数据库只关闭一次。

## 任务 1：锁定现有 UI 行为

**测试：** 修改 `tests/integration/test_main_window.py`。

- [ ] 增加快照刷新测试，固定九页标签、所有按钮文字、轨道/信号/报文/限速/网络/日志字段。
- [ ] 增加单站关闭所有权测试：实际 `ApplicationRuntime.stop()` 已关闭 controller 时，窗口不再二次 close。
- [ ] 运行测试确认二次关闭用例先失败。

## 任务 2：提取可嵌入单站组件

**文件：** 新建 `app/ui/station_detail_widget.py`；修改 `app/ui/main_window.py`。

**接口：**

```python
class StationDetailWidget(QWidget):
    operation_completed = pyqtSignal(object)

    def __init__(self, controller: TccController, *, include_train_page: bool = True) -> None: ...
    def refresh(self, snapshot: TccSnapshot) -> None: ...
    def stop_activity(self) -> None: ...

class TccMainWindow(QMainWindow):
    def __init__(self, controller: TccController, *, lifecycle: RuntimeLifecyclePort | None = None) -> None: ...
```

- [ ] 把九页构建、表格填充和命令槽原样迁移到 `StationDetailWidget`，每个方法保持单一职责。
- [ ] `StationDetailWidget` 不实现 `closeEvent`，不停止网络、不关闭 repository。
- [ ] `TccMainWindow` 嵌入该组件，关闭时先 `stop_activity()`，再调用 lifecycle；无 lifecycle 的测试模式才直接关闭 controller。
- [ ] 运行原 UI 测试，确保行为和文本无回归。

## 任务 3：集中经典控制台主题

**文件：** 新建 `app/ui/styles.py`；测试 `tests/unit/test_ui_styles.py`。

**接口：**

```python
CLASSIC_CONSOLE_QSS: str

def repolish(widget: QWidget) -> None: ...
def set_semantic_state(widget: QWidget, property_name: str, value: str) -> None: ...
```

- [ ] 测试 QSS 包含设计基线规定的标题蓝、导航选中蓝、面板白、边框灰和状态属性选择器。
- [ ] 使用动态属性 `severity`、`connectionState`、`trackState`，设置后调用 unpolish/polish。
- [ ] 从 `main_window.py` 删除长内联 QSS，单站窗口应用集中主题。
- [ ] 禁止硬编码微软雅黑；使用系统字体和 point size。

## 任务 4：视觉与兼容验收

- [ ] pytest-qt 检查 1280×800 时九页可访问、关键按钮可见、表格可滚动。
- [ ] 生成单站 A/B 离屏截图，人工对照参考图方案一：浅色背景、蓝色标题/导航、细边框、紧凑表格。
- [ ] 运行全量测试、compileall、单站实际启动和 `git diff --check`。
- [ ] 更新防中断文档；独立复审无 Critical/Important 后提交：

```bash
git add app/ui tests docs/IMPLEMENTATION_STATUS.md
git commit -m "refactor: extract reusable station control widget"
git push origin codex/dual-station-dashboard
```

## 验收门

单站九页功能不变；组件可嵌入任意父窗口；生命周期没有二次关闭；视觉符合经典控制台；全量测试通过。

## Codex 执行提示词

```text
执行双站同屏阶段 2。读设计基线、本文件和现有 main_window.py。先补测试锁定九页功能，再把业务页面提取为 StationDetailWidget；组件只发控制器命令和显示快照，不拥有网络/数据库关闭。TccMainWindow 仅作兼容壳。集中实现参考图方案一的浅色经典控制台 QSS，禁止深色卡片、固定坐标、硬编码字体和空按钮。验证 1280×800、单站入口、全量回归，复审后提交推送。
```
