from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class SimulationEngine(QObject):

    updated = pyqtSignal()

    train_dispatched = pyqtSignal(str)

    def __init__(self, train_service, parent=None):
        super().__init__(parent)

        self.train_service = train_service

        # 每100毫秒更新一次
        self.interval_ms = 100

        # 仿真倍速
        self.speed_multiplier = 1.0

        # 仿真累计时间
        self.simulation_time = 0.0

        self.timer = QTimer(self)

        self.timer.setInterval(
            self.interval_ms
        )

        self.timer.timeout.connect(
            self.update_simulation
        )

    def start(self):
        if not self.timer.isActive():
            self.timer.start()

    def pause(self):
        self.timer.stop()

    def reset_time(self):
        self.simulation_time = 0.0

    def set_speed_multiplier(self, value):
        self.speed_multiplier = float(value)

    def update_simulation(self):

        # 100ms = 0.1秒
        delta_time = (
            self.interval_ms / 1000.0
        )

        delta_time *= self.speed_multiplier

        self.simulation_time += delta_time

        dispatched = (
            self.train_service.update_all(
                delta_time
            )
        )

        if dispatched is not None:
            self.train_dispatched.emit(
                dispatched.train_id
            )

        self.updated.emit()