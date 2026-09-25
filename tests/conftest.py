"""GUI 测试统一使用无窗口平台，避免依赖显示器。"""

import os
from pathlib import Path

import PyQt5


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    str(Path(next(iter(PyQt5.__path__))) / "Qt5" / "plugins" / "platforms"),
)
