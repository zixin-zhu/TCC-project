"""TCC 单站兼容窗口；业务页面与资源生命周期职责分离。"""

from __future__ import annotations

from typing import Protocol

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QMainWindow

from app.services.tcc_controller import TccController
from app.ui.station_detail_widget import StationDetailWidget
from app.ui.styles import CLASSIC_CONSOLE_QSS


class RuntimeLifecyclePort(Protocol):
    """正式运行时在停止网络线程后自行关闭控制器与数据库。"""

    def stop(self, *, timeout_ms: int = 3000) -> bool: ...


class TccMainWindow(QMainWindow):
    """保留单站入口，并把九页功能委托给可复用详情组件。"""

    def __init__(
        self,
        controller: TccController,
        *,
        lifecycle: RuntimeLifecyclePort | None = None,
        network_thread: RuntimeLifecyclePort | None = None,
    ) -> None:
        super().__init__()
        if lifecycle is not None and network_thread is not None:
            raise ValueError("lifecycle 与兼容参数 network_thread 不能同时提供")
        self.controller = controller
        # `network_thread` 是旧入口兼容名；ApplicationRuntime 实际拥有完整生命周期。
        self.lifecycle = lifecycle if lifecycle is not None else network_thread
        self.detail = StationDetailWidget(controller)
        self.setCentralWidget(self.detail)
        self.setWindowTitle("高铁车站列控中心 TCC 功能仿真系统")
        self.resize(1280, 820)
        self.setStyleSheet(CLASSIC_CONSOLE_QSS)
        self._closed = False
        self._publish_compatibility_attributes()

    def _publish_compatibility_attributes(self) -> None:
        """保留既有自动化/演示脚本访问的公开控件名。"""
        for name, value in vars(self.detail).items():
            if not name.startswith("_") and not hasattr(self, name):
                setattr(self, name, value)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._closed:
            event.accept()
            return

        train_was_running = self.detail.train_timer.isActive()
        self.detail.stop_activity()
        if self.lifecycle is not None:
            if not self.lifecycle.stop(timeout_ms=3000):
                if train_was_running:
                    self.detail.train_timer.start()
                self.detail.operation_result.setText(
                    "关闭被拒绝：运行时线程未在超时内停止"
                )
                event.ignore()
                return
        else:
            # 仅用于无 ApplicationRuntime 的测试/嵌入模式；正式入口由 runtime 关闭。
            self.controller.close()
        self._closed = True
        event.accept()
