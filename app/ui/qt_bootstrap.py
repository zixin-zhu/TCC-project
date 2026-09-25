"""在创建 QApplication 前修复 Qt 5 对中文安装路径的插件定位。"""

import os
from pathlib import Path

import PyQt5
from PyQt5.QtCore import QLibraryInfo


def configure_qt_plugin_path() -> None:
    """仅在 Qt 报告路径不可用时设置本进程的平台插件目录。"""
    reported = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
    if reported.is_dir():
        return
    derived = Path(next(iter(PyQt5.__path__))) / "Qt5" / "plugins" / "platforms"
    if derived.is_dir():
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(derived))
