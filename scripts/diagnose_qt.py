"""输出 PyQt5 环境信息，辅助定位 macOS 平台插件问题。

脚本只读取环境，不设置 QT_PLUGIN_PATH 等全局变量。
"""

import platform
import sys
from pathlib import Path

import PyQt5
from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QLibraryInfo


def main() -> int:
    reported_path = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
    # Qt 5 在某些 macOS 环境中会把安装前缀里的非 ASCII 字符替换成问号。
    # 诊断脚本在该路径不存在时，从已成功导入的 PyQt5 包位置反推插件目录，
    # 既保留 Qt 的原始报告，也避免把编码问题误报成“插件未安装”。
    package_path = Path(next(iter(PyQt5.__path__)))
    derived_path = package_path / "Qt5" / "plugins"
    plugin_path = reported_path if reported_path.is_dir() else derived_path
    platforms_path = plugin_path / "platforms"
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"PyQt5: {PYQT_VERSION_STR}")
    print(f"Qt: {QT_VERSION_STR}")
    print(f"Qt plugins: {plugin_path}")
    if plugin_path != reported_path:
        print(f"Qt reported plugins path (unusable): {reported_path}")
    print(f"Platform plugins directory exists: {platforms_path.is_dir()}")
    if sys.platform == "darwin":
        print(f"macOS cocoa plugin exists: {(platforms_path / 'libqcocoa.dylib').is_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
