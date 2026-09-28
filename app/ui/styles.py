"""TCC 界面统一的经典浅色工业控制台主题与输入控件策略。"""

from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QComboBox, QWidget


CLASSIC_CONSOLE_QSS = """
QMainWindow, QWidget#stationDetailRoot, QWidget#dualMainRoot {
    background: #eef2f5;
    color: #1f2d38;
}
QWidget#consoleHeader {
    background: #07558f;
}
QLabel#applicationTitle {
    background: transparent;
    color: #ffffff;
    padding: 9px 14px;
    font-size: 16pt;
    font-weight: 600;
}
QLabel#stationIdentity {
    background: transparent;
    color: #ffffff;
    font-size: 11pt;
    font-weight: 600;
    padding: 6px;
}
QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #b8c7d3;
}
QTabBar::tab {
    background: #e5ebf0;
    color: #1f2d38;
    border: 1px solid #b8c7d3;
    border-bottom: 0;
    padding: 7px 14px;
}
QTabBar::tab:selected {
    background: #1976d2;
    color: #ffffff;
}
QListWidget#sideNavigation {
    background: #e5ebf0;
    color: #1f2d38;
    border: 1px solid #b8c7d3;
    outline: 0;
}
QListWidget#sideNavigation::item {
    min-height: 30px;
    padding: 4px 8px;
    border-bottom: 1px solid #d4dde4;
}
QListWidget#sideNavigation::item:selected {
    background: #1976d2;
    color: #ffffff;
}
QFrame#globalStatusBar {
    background: #ffffff;
    border: 1px solid #b8c7d3;
}
QLabel#pageHeading {
    color: #07558f;
    font-size: 13pt;
    font-weight: 600;
    padding: 6px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #b8c7d3;
    border-radius: 3px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 9px;
    color: #07558f;
    background: #e7f0f7;
    padding: 1px 5px;
}
QPushButton {
    min-height: 24px;
    background: #1976d2;
    color: #ffffff;
    border: 1px solid #1267b7;
    border-radius: 3px;
    padding: 3px 12px;
}
QPushButton:hover { background: #0b6cad; }
QPushButton:pressed { background: #07558f; }
QPushButton:disabled {
    background: #d5dde3;
    color: #71808c;
    border-color: #b8c7d3;
}
QTableWidget, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    color: #1f2d38;
    border: 1px solid #b8c7d3;
    gridline-color: #d7e0e7;
    selection-background-color: #c8e1f5;
    selection-color: #1f2d38;
}
QComboBox {
    min-height: 28px;
    padding: 2px 30px 2px 8px;
}
QComboBox::drop-down {
    width: 26px;
    border-left: 1px solid #b8c7d3;
}
QComboBox QAbstractItemView {
    padding: 2px;
    selection-background-color: #c8e1f5;
    selection-color: #1f2d38;
}
QHeaderView::section {
    background: #dbe8f2;
    color: #1f2d38;
    border: 0;
    border-right: 1px solid #b8c7d3;
    border-bottom: 1px solid #b8c7d3;
    padding: 4px;
}
QLabel#operationResult { padding: 5px 8px; }
QWidget[severity="info"] { color: #07558f; }
QWidget[severity="warning"] { color: #9a6400; }
QWidget[severity="critical"] { color: #b42318; font-weight: 600; }
QWidget[connectionState="HEALTHY"] { color: #167545; font-weight: 600; }
QWidget[connectionState="DEGRADED"] { color: #9a6400; font-weight: 600; }
QWidget[connectionState="DISCONNECTED"] { color: #b42318; font-weight: 600; }
QWidget[trackState="CLEAR"] { color: #33424e; }
QWidget[trackState="OCCUPIED"] { color: #c62828; font-weight: 600; }
QWidget[trackState="FAULT_OCCUPIED"] { color: #7b1fa2; font-weight: 600; }
QWidget[trackState="SHUNT_BAD"] { color: #c05a00; font-weight: 600; }
"""


COMBO_ROLE_MIN_WIDTHS = {
    "station": 100,
    "section": 130,
    "state": 140,
    "signal": 120,
    "route": 180,
    "direction": 160,
    "tsr": 170,
    "shared": 150,
    "train": 220,
    "simulation-speed": 120,
}


def configure_combo_box(
    combo: QComboBox,
    role: str,
    *,
    min_width: int | None = None,
) -> QComboBox:
    """统一设置下拉框宽度，并让动态选项和可编辑文本触发重新测量。

    ``role`` 表达字段语义而不是页面位置，便于双站操作页和单站详情页共享
    同一套宽度基线。弹出列表额外按字体实际宽度测量，避免长区段、进路或
    临时限速编号被截断；这里不使用全局超大固定宽度，保留经典控制台的紧凑
    布局。
    """
    if not isinstance(combo, QComboBox):
        raise TypeError("configure_combo_box 只接受 QComboBox")
    if role not in COMBO_ROLE_MIN_WIDTHS:
        raise ValueError(f"未知下拉框角色：{role}")
    if combo.property("comboRole") is not None:
        return combo

    baseline = max(COMBO_ROLE_MIN_WIDTHS[role], min_width or 0)
    combo.setProperty("comboRole", role)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def resize_to_contents(*_args: object) -> None:
        metrics = QFontMetrics(combo.font())
        content_width = max(
            (metrics.horizontalAdvance(combo.itemText(index)) for index in range(combo.count())),
            default=0,
        )
        if combo.isEditable() and combo.lineEdit() is not None:
            content_width = max(
                content_width,
                metrics.horizontalAdvance(combo.lineEdit().text()),
            )
        # 左右内边距、下拉箭头和边框预留空间，确保显示文本而非只显示省略号。
        width = max(baseline, content_width + 48)
        combo.setMinimumWidth(width)
        combo.view().setMinimumWidth(width)
        if combo.lineEdit() is not None:
            combo.lineEdit().setMinimumWidth(width)

    model = combo.model()
    model.rowsInserted.connect(resize_to_contents)
    model.rowsRemoved.connect(resize_to_contents)
    model.modelReset.connect(resize_to_contents)
    model.dataChanged.connect(resize_to_contents)
    combo.currentTextChanged.connect(resize_to_contents)
    resize_to_contents()
    return combo


def repolish(widget: QWidget) -> None:
    """动态属性变化后立即让 Qt 重新匹配 QSS 选择器。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_semantic_state(widget: QWidget, property_name: str, value: str) -> None:
    """设置状态语义；颜色只是辅助手段，控件文本仍须表达完整状态。"""
    if widget.property(property_name) == value:
        return
    widget.setProperty(property_name, value)
    repolish(widget)


def relay_text(relay: bool) -> str:
    """把继电器吸起/落下布尔值统一成控制台风格的 1/0 显示。

    全项目信号灯丝/继电器状态统一采用“1=吸起(点亮)、0=落下(熄灭)”，
    避免同一数据在不同页面出现 True/False 与 1/0 混用。
    """
    return "1" if relay else "0"
