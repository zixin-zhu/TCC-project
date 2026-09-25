"""TCC 界面统一的经典浅色工业控制台主题。"""

from PyQt5.QtWidgets import QWidget


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
