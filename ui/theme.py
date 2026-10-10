APP_STYLESHEET = """
QMainWindow, QWidget#app_root {
    background: #eef2f6;
    color: #1d2a36;
    font-family: "Microsoft YaHei", "PingFang SC";
    font-size: 13px;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #d7e0e8;
    border-radius: 9px;
    margin-top: 11px;
    padding-top: 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #30465b;
}

QGroupBox#visualization_area {
    background: #05070a;
    border: 1px solid #233443;
}

QGroupBox#visualization_area::title {
    color: #d9e7f2;
}

QGroupBox#communication_area, QGroupBox#operation_area {
    background: #f9fbfd;
}

QPushButton {
    min-height: 30px;
    padding: 0 12px;
    border: 1px solid #c8d3dd;
    border-radius: 6px;
    background: #ffffff;
    color: #223447;
}

QPushButton:hover {
    border-color: #2f83c5;
    background: #eef7ff;
}

QPushButton:pressed {
    background: #dceefe;
}

QPushButton:disabled {
    color: #95a2ae;
    background: #eef1f4;
}

QComboBox {
    min-height: 28px;
    padding: 0 8px;
    border: 1px solid #c8d3dd;
    border-radius: 5px;
    background: #ffffff;
}

QComboBox QAbstractItemView {
    color: #1d2a36;
    background: #ffffff;
    selection-color: #ffffff;
    selection-background-color: #2f83c5;
    outline: 0;
}

QComboBox QAbstractItemView::item {
    min-height: 28px;
}

QComboBox QAbstractItemView::item:selected {
    color: #ffffff;
    background-color: #2f83c5;
}
"""
