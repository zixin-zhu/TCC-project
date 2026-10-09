from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QComboBox,
    QMessageBox,
    QSizePolicy
)

from services.simulation_service import SimulationService
from services.train_service import TrainService
from services.simulation_engine import SimulationEngine
from services.direction_manager import DirectionManager
from services.temporary_speed_service import TemporarySpeedService

from network.message_protocol import MessageProtocol
from network.network_worker import (
    ServerNetworkWorker
)

from ui.station_panel import StationPanel
from ui.tcc_overview import HorizontalWheelScrollArea, TccOverviewWidget
from ui.theme import APP_STYLESHEET


class MainWindow(QMainWindow):
    """
    单窗口双TCC架构。

    窗口里同时存在两个相互独立的TCC对象：

    TCC_A（simulation_a）
        通信角色 Server，信号机 S01，自有38个轨道区段

    TCC_B（simulation_b）
        通信角色 Server，信号机 S02，自有38个轨道区段

    两者分别监听本机9000和9001端口，
    对等通信协议将在通信阶段实现。

    列车仿真（TrainService）挂在A侧，
    B侧通过报文镜像区间占用后自行重算。
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "高铁车站列控中心 TCC 功能仿真系统"
        )

        self.resize(
            1440,
            900
        )
        self.setMinimumSize(1180, 760)
        self.setStyleSheet(APP_STYLESHEET)

        # ==========================
        # 双TCC后台服务
        # ==========================

        # A站TCC，通信角色Server
        self.simulation_a = SimulationService("A")

        # B站TCC，通信角色Server
        self.simulation_b = SimulationService("B")

        # 列车仿真始终挂在A侧
        self.train_service = TrainService(
            self.simulation_a
        )

        self.temporary_speed_service = TemporarySpeedService(
            list(self.simulation_a.track_circuits.keys())
        )

        self.engine = SimulationEngine(
            self.train_service
        )

        self.engine.updated.connect(
            self.refresh_view
        )

        self.engine.train_dispatched.connect(
            self.on_train_dispatched
        )

        # ==========================
        # 两侧改方管理器
        # ==========================

        self.direction_manager_a = DirectionManager(
            self.simulation_a,
            "TCC_A",
            "A"
        )

        self.direction_manager_b = DirectionManager(
            self.simulation_b,
            "TCC_B",
            "B"
        )

        # 站间通信端点：{站别: worker}
        self.network_workers = {}

        # 站间同步节拍计数
        self.network_tick = 0

        self.init_ui()

        self.apply_network_mode()

        self.refresh_view()

    def init_ui(self):

        central = QWidget()
        central.setObjectName("app_root")

        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(
            central
        )
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(10)

        self.visualization_area = QGroupBox()
        self.visualization_area.setObjectName(
            "visualization_area"
        )

        visualization_layout = QVBoxLayout(
            self.visualization_area
        )
        visualization_layout.setContentsMargins(5, 5, 5, 5)

        # ==========================
        # A/B站控制中心
        # ==========================

        self.communication_area = QGroupBox(
            "站间通信"
        )
        self.communication_area.setObjectName(
            "communication_area"
        )
        self.communication_area.setMinimumWidth(270)
        self.communication_area.setMaximumWidth(320)

        station_layout = QVBoxLayout(
            self.communication_area
        )
        station_layout.setContentsMargins(9, 10, 9, 9)
        station_layout.setSpacing(8)

        self.panel_a = StationPanel("A")
        self.panel_b = StationPanel("B")

        station_layout.addWidget(
            self.panel_a
        )

        station_layout.addWidget(
            self.panel_b
        )

        # ==========================
        # 动态线路
        # ==========================

        self.simulation_view = (
            TccOverviewWidget()
        )

        self.visualization_scroll_area = HorizontalWheelScrollArea()
        self.visualization_scroll_area.setObjectName(
            "visualization_scroll_area"
        )
        self.visualization_scroll_area.setWidgetResizable(True)
        self.visualization_scroll_area.setVerticalScrollBarPolicy(
            1
        )
        self.visualization_scroll_area.setWidget(
            self.simulation_view
        )

        visualization_layout.addWidget(
            self.visualization_scroll_area
        )

        main_layout.addWidget(
            self.visualization_area,
            9
        )

        # ==========================================
        # 列车实时状态面板
        # ==========================================

        self.operation_area = QGroupBox(
            "仿真操作"
        )
        self.operation_area.setObjectName(
            "operation_area"
        )
        operation_layout = QVBoxLayout(
            self.operation_area
        )
        operation_layout.setContentsMargins(8, 8, 8, 8)
        operation_layout.setSpacing(5)

        self.operation_top_layout = QHBoxLayout()
        self.operation_top_layout.setSpacing(7)

        direction_group = QGroupBox("区间改方")
        direction_group.setObjectName("direction_change_area")
        direction_group_layout = QVBoxLayout(direction_group)
        direction_group_layout.setContentsMargins(8, 8, 8, 8)
        direction_group_layout.setSpacing(5)
        self.panel_a.direction_button.setText("A站申请区间改方")
        self.panel_b.direction_button.setText("B站申请区间改方")
        direction_group_layout.addWidget(self.panel_a.direction_button)
        direction_group_layout.addWidget(self.panel_b.direction_button)

        equipment_group = QGroupBox(
            "临时限速"
        )
        equipment_group.setObjectName("temporary_speed_area")
        equipment_layout = QGridLayout(
            equipment_group
        )

        equipment_layout.addWidget(QLabel("起始区段："), 0, 0)
        self.tsr_start_combo = QComboBox()
        self.tsr_start_combo.setObjectName("tsr_start_section")
        self.tsr_start_combo.addItems([f"G{i:02d}" for i in range(1, 39)])
        equipment_layout.addWidget(self.tsr_start_combo, 0, 1)

        equipment_layout.addWidget(QLabel("终止区段："), 0, 2)
        self.tsr_end_combo = QComboBox()
        self.tsr_end_combo.setObjectName("tsr_end_section")
        self.tsr_end_combo.addItems([f"G{i:02d}" for i in range(1, 39)])
        equipment_layout.addWidget(self.tsr_end_combo, 0, 3)

        equipment_layout.addWidget(QLabel("限速："), 0, 4)
        self.tsr_speed_combo = QComboBox()
        self.tsr_speed_combo.setObjectName("tsr_speed")
        self.tsr_speed_combo.addItems(["45 km/h", "80 km/h", "120 km/h", "160 km/h", "200 km/h", "250 km/h"])
        equipment_layout.addWidget(self.tsr_speed_combo, 0, 5)

        self.tsr_apply_button = QPushButton("设置限速")
        self.tsr_apply_button.setObjectName("tsr_apply_button")
        equipment_layout.addWidget(self.tsr_apply_button, 0, 6)

        self.active_tsr_combo = QComboBox()
        self.active_tsr_combo.setObjectName("active_tsr")
        equipment_layout.addWidget(QLabel("已生效限速："), 1, 0)
        equipment_layout.addWidget(self.active_tsr_combo, 1, 1, 1, 5)

        self.tsr_cancel_button = QPushButton("取消选中限速")
        self.tsr_cancel_button.setObjectName("tsr_cancel_button")
        equipment_layout.addWidget(self.tsr_cancel_button, 1, 6)

        self.operation_top_layout.addWidget(direction_group, 1)
        self.operation_top_layout.addWidget(equipment_group, 3)
        operation_layout.addLayout(self.operation_top_layout)

        train_info_group = QGroupBox(
            "列车实时运行状态"
        )

        train_info_layout = QVBoxLayout(
            train_info_group
        )
        train_info_layout.setContentsMargins(8, 8, 8, 8)
        train_info_layout.setSpacing(5)

        self.train_selector_layout = QHBoxLayout()
        self.train_selector_layout.setSpacing(4)

        # 列车选择
        self.train_selector_layout.addWidget(
            QLabel("查看列车："),
        )

        self.train_selector = QComboBox()
        self.train_selector.setMinimumWidth(150)

        self.train_selector_layout.addWidget(self.train_selector)
        self.train_selector_layout.addSpacing(10)

        self.train_selector_layout.addWidget(QLabel("发车方式："))
        self.departure_mode_combo = QComboBox()
        self.departure_mode_combo.addItems(["正线发车", "侧线发车"])
        self.departure_mode_combo.setMinimumWidth(120)
        self.train_selector_layout.addWidget(self.departure_mode_combo)
        self.train_selector_layout.addSpacing(10)

        self.train_selector_layout.addWidget(QLabel("接车方式："))
        self.arrival_mode_combo = QComboBox()
        self.arrival_mode_combo.addItems(["正线接车", "侧线接车"])
        self.arrival_mode_combo.setMinimumWidth(120)
        self.train_selector_layout.addWidget(self.arrival_mode_combo)
        self.train_selector_layout.addStretch()
        train_info_layout.addLayout(self.train_selector_layout)

        self.train_status_grid = QGridLayout()
        self.train_status_grid.setHorizontalSpacing(14)
        self.train_status_grid.setVerticalSpacing(4)

        # 第一行
        self.info_track = QLabel(
            "当前分区：--"
        )

        self.info_position = QLabel(
            "分区位置：--"
        )

        self.info_speed = QLabel(
            "当前速度：--"
        )

        self.info_target = QLabel(
            "目标速度：--"
        )

        self.train_status_grid.addWidget(
            self.info_track,
            0,
            0
        )

        self.train_status_grid.addWidget(
            self.info_position,
            0,
            1
        )

        self.train_status_grid.addWidget(
            self.info_speed,
            0,
            2
        )

        self.train_status_grid.addWidget(
            self.info_target,
            0,
            3
        )

        # 第二行
        self.info_code = QLabel(
            "当前码序：--"
        )

        self.info_line_speed = QLabel(
            "线路限速：--"
        )

        self.info_balise = QLabel(
            "最后应答器：--"
        )

        self.info_safety = QLabel(
            "安全状态：--"
        )

        self.train_status_grid.addWidget(
            self.info_code,
            1,
            0
        )

        self.train_status_grid.addWidget(
            self.info_line_speed,
            1,
            1
        )

        self.train_status_grid.addWidget(
            self.info_balise,
            1,
            2
        )

        self.train_status_grid.addWidget(
            self.info_safety,
            1,
            3
        )

        # 第三行
        self.info_distance = QLabel(
            "前车距离：--"
        )

        self.info_braking = QLabel(
            "制动距离：--"
        )

        self.train_status_grid.addWidget(
            self.info_distance,
            0,
            4
        )

        self.train_status_grid.addWidget(
            self.info_braking,
            1,
            4
        )

        train_info_layout.addLayout(self.train_status_grid)

        operation_layout.addWidget(
            train_info_group
        )

        # ==========================
        # 仿真控制栏
        # ==========================

        control_layout = QHBoxLayout()

        self.add_train_button = QPushButton(
            "添加待发列车"
        )

        self.start_button = QPushButton(
            "▶ 开始仿真"
        )

        self.pause_button = QPushButton(
            "Ⅱ 暂停"
        )

        self.reset_button = QPushButton(
            "■ 复位"
        )

        self.clear_trains_button = QPushButton(
            "一键清车"
        )

        self.speed_combo = QComboBox()

        self.speed_combo.addItems(
            [
                "0.5×",
                "1×",
                "2×",
                "5×"
            ]
        )

        self.speed_combo.setCurrentText(
            "1×"
        )

        self.running_label = QLabel(
            "运行列车：0"
        )

        self.queue_label = QLabel(
            "待发列车：0"
        )

        self.time_label = QLabel(
            "仿真时间：0.0 s"
        )

        control_layout.addWidget(
            self.add_train_button
        )

        control_layout.addWidget(
            self.start_button
        )

        control_layout.addWidget(
            self.pause_button
        )

        control_layout.addWidget(
            self.reset_button
        )

        control_layout.addWidget(
            self.clear_trains_button
        )

        control_layout.addWidget(
            QLabel("仿真倍速：")
        )

        control_layout.addWidget(
            self.speed_combo
        )

        control_layout.addStretch()

        operation_layout.addLayout(
            control_layout
        )

        metrics_layout = QHBoxLayout()
        metrics_layout.addWidget(self.running_label)
        metrics_layout.addWidget(self.queue_label)
        metrics_layout.addWidget(self.time_label)
        metrics_layout.addStretch()
        operation_layout.addLayout(metrics_layout)

        self.bottom_widget = QWidget()
        self.bottom_widget.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Maximum
        )
        bottom_layout = QHBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(self.communication_area)
        bottom_layout.addWidget(self.operation_area, 1)

        main_layout.addWidget(self.bottom_widget, 3)

        # ==========================
        # 绑定
        # ==========================

        self.add_train_button.clicked.connect(
            self.add_waiting_train
        )

        self.start_button.clicked.connect(
            self.start_simulation
        )

        self.pause_button.clicked.connect(
            self.pause_simulation
        )

        self.reset_button.clicked.connect(
            self.reset_simulation
        )

        self.clear_trains_button.clicked.connect(
            self.clear_all_trains
        )

        self.speed_combo.currentTextChanged.connect(
            self.change_speed
        )

        self.tsr_apply_button.clicked.connect(
            self.apply_temporary_speed_restriction
        )

        self.tsr_cancel_button.clicked.connect(
            self.cancel_temporary_speed_restriction
        )

        self.simulation_view.balise_clicked.connect(
            self.show_balise_information
        )

    # ==============================
    # 添加待发列车
    # ==============================

    def add_waiting_train(self):

        train = (
            self.train_service.add_waiting_train()
        )

        print(
            f"{train.train_id} 已加入待发队列"
        )

        self.refresh_view()

    # ==============================
    # 开始
    # ==============================

    def start_simulation(self):

        self.engine.start()

        self.start_button.setEnabled(
            False
        )

        self.pause_button.setEnabled(
            True
        )

    # ==============================
    # 暂停
    # ==============================

    def pause_simulation(self):

        self.engine.pause()

        self.start_button.setEnabled(
            True
        )

    # ==============================
    # 倍速
    # ==============================

    def change_speed(self, text):

        value = float(
            text.replace(
                "×",
                ""
            )
        )

        self.engine.set_speed_multiplier(
            value
        )

    def apply_temporary_speed_restriction(self):
        try:
            speed = int(self.tsr_speed_combo.currentText().split()[0])
            self.temporary_speed_service.set_restriction(
                self.tsr_start_combo.currentText(),
                self.tsr_end_combo.currentText(),
                speed,
            )
        except ValueError as error:
            QMessageBox.warning(self, "限速设置失败", str(error))
            return
        self.refresh_temporary_speed_controls()
        self.refresh_view()

    def cancel_temporary_speed_restriction(self):
        restriction_id = self.active_tsr_combo.currentData()
        if restriction_id is None:
            return
        self.temporary_speed_service.cancel_restriction(restriction_id)
        self.refresh_temporary_speed_controls()
        self.refresh_view()

    def refresh_temporary_speed_controls(self):
        current_id = self.active_tsr_combo.currentData()
        self.active_tsr_combo.clear()
        for restriction in self.temporary_speed_service.active_restrictions():
            text = (
                f"{restriction['id']}  "
                f"{restriction['start_section']}～{restriction['end_section']}  "
                f"{restriction['speed_kmh']} km/h"
            )
            self.active_tsr_combo.addItem(text, restriction["id"])
        if current_id is not None:
            index = self.active_tsr_combo.findData(current_id)
            if index >= 0:
                self.active_tsr_combo.setCurrentIndex(index)

    def clear_all_trains(self):
        self.engine.pause()
        self.train_service.clear_all_trains()
        for simulation in (self.simulation_a, self.simulation_b):
            simulation.train_position = None
            for track in simulation.track_circuits.values():
                track.release()
            simulation.close_signal()
            simulation.update_all_track_codes()
        self.start_button.setEnabled(True)
        self.refresh_view()

    def get_balise_information(self, balise_id):
        if not self.is_connected():
            packets = ["ETCS-254"]
        else:
            packets = ["ETCS-5", "ETCS-21", "ETCS-27"]
            if self.temporary_speed_service.active_restrictions():
                packets.append("ETCS-44(CTCS-2)")
        return {
            "balise_id": balise_id,
            "packets": packets,
            "direction": self.simulation_a.get_direction(),
        }

    def show_balise_information(self, balise_id):
        info = self.get_balise_information(balise_id)
        QMessageBox.information(
            self,
            "有源应答器信息",
            f"应答器组：{info['balise_id']}\n"
            f"运行方向：{info['direction']}\n"
            f"信息包：{', '.join(info['packets'])}",
        )

    # ==============================
    # 自动发车事件
    # ==============================

    def on_train_dispatched(
        self,
        train_id
    ):

        print(
            f"{train_id} 自动发车"
        )

    # ==============================
    # 复位
    # ==============================

    def reset_simulation(self):

        self.engine.pause()

        # 重新创建列车服务（列车仿真始终挂A侧）
        self.train_service = TrainService(
            self.simulation_a
        )

        # Engine改为使用新的服务
        self.engine.train_service = (
            self.train_service
        )

        # 清空两侧TCC的轨道占用
        for simulation in (
                self.simulation_a,
                self.simulation_b
        ):

            for track in (
                    simulation
                    .track_circuits
                    .values()
            ):
                track.release()

            simulation.update_all_track_codes()

        self.engine.reset_time()

        self.start_button.setEnabled(
            True
        )

        self.refresh_view()

    # ==============================
    # 刷新
    # ==============================

    def refresh_view(self):

        # 线路占用以A侧（列车仿真侧）为准
        tracks = (
            self.simulation_a.get_all_track_status()
        )

        for train in self.train_service.trains.values():
            temporary_speed = self.temporary_speed_service.speed_for(
                train.current_track
            )
            train.temporary_speed = (
                float(temporary_speed)
                if temporary_speed is not None
                else train.max_speed
            )
            train.calculate_target_speed()

        trains = self.train_service.get_all_train_status()

        direction = (
            self.simulation_a.get_direction()
        )

        # 两侧信号机各自用自己的自动闭塞结果
        signal_status_a = (
            self.simulation_a
            .update_signal_status()
        )

        signal_status_b = (
            self.simulation_b
            .update_signal_status()
        )

        # A面板只认TCC_A的S01，B面板只认TCC_B的S02
        signal_a = signal_status_a["S01"]
        signal_b = signal_status_b["S02"]

        # 两站控制面板
        self.panel_a.set_signal_status(
            signal_a
        )

        self.panel_b.set_signal_status(
            signal_b
        )

        # 两个控制中心各自显示自己TCC的运行方向
        self.panel_a.set_direction_status(
            self.simulation_a.get_direction()
        )

        self.panel_b.set_direction_status(
            self.simulation_b.get_direction()
        )

        # 动态线路
        self.simulation_view.set_state(
            tracks=tracks,
            trains=trains,
            direction=direction,
            signal_a=signal_a,
            signal_b=signal_b,
            restrictions=(
                self.temporary_speed_service.active_restrictions()
            ),
        )

        self.update_train_selector(
            trains
        )

        self.refresh_train_info(
            trains
        )

        # --------------------------
        # 统计
        # --------------------------

        running_count = 0

        for train in (
            self.train_service.trains.values()
        ):

            if train.status in (
                "RUNNING",
                "STOPPED"
            ):
                running_count += 1

        self.running_label.setText(
            f"运行列车：{running_count}"
        )

        self.queue_label.setText(
            f"待发列车："
            f"{len(self.train_service.waiting_queue)}"
        )

        self.time_label.setText(
            f"仿真时间："
            f"{self.engine.simulation_time:.1f} s"
        )

        # --------------------------
        # 站间同步
        # --------------------------

        self.network_tick += 1

        if self.network_tick % 2 == 0:
            self.send_track_status()

    def update_train_selector(
            self,
            trains
    ):

        current_id = (
            self.train_selector.currentText()
        )

        train_ids = [
            train.get("train_id")
            for train in trains
            if train.get("train_id")
        ]

        existing_ids = [
            self.train_selector.itemText(i)
            for i in range(
                self.train_selector.count()
            )
        ]

        if train_ids != existing_ids:

            self.train_selector.blockSignals(
                True
            )

            self.train_selector.clear()

            self.train_selector.addItems(
                train_ids
            )

            if current_id in train_ids:
                self.train_selector.setCurrentText(
                    current_id
                )

            self.train_selector.blockSignals(
                False
            )

    def refresh_train_info(
            self,
            trains
    ):

        selected_id = (
            self.train_selector.currentText()
        )

        if not selected_id:
            self.clear_train_info()
            return

        selected_train = None

        for train in trains:

            if (
                    train.get("train_id")
                    == selected_id
            ):
                selected_train = train
                break

        if selected_train is None:
            self.clear_train_info()
            return

        # ==========================================
        # 基本运行信息
        # ==========================================

        self.info_track.setText(
            f"当前分区："
            f"{selected_train.get('current_track') or '--'}"
        )

        self.info_position.setText(
            f"分区位置："
            f"{selected_train.get('position', 0):.0f} m"
        )

        self.info_speed.setText(
            f"当前速度："
            f"{selected_train.get('speed', 0):.1f} km/h"
        )

        self.info_target.setText(
            f"目标速度："
            f"{selected_train.get('target_speed', 0):.1f} km/h"
        )

        # ==========================================
        # 控制信息
        # ==========================================

        self.info_code.setText(
            f"当前码序："
            f"{selected_train.get('block_code', '--')}"
        )

        self.info_line_speed.setText(
            f"线路限速："
            f"{selected_train.get('line_speed', 0):.0f} km/h"
        )

        self.info_balise.setText(
            f"最后应答器："
            f"{selected_train.get('last_balise') or '--'}"
        )

        safety = selected_train.get(
            "safety_status",
            "CLEAR"
        )

        self.info_safety.setText(
            f"安全状态：{safety}"
        )
        if safety in (
                "CLEAR",
                "SAFE"
        ):

            self.info_safety.setStyleSheet(
                "color: green; font-weight: bold;"
            )

        elif safety == "WARNING":

            self.info_safety.setStyleSheet(
                "color: #C58A00; font-weight: bold;"
            )

        elif safety == "DANGER":

            self.info_safety.setStyleSheet(
                "color: red; font-weight: bold;"
            )

        else:

            self.info_safety.setStyleSheet("")

        # ==========================================
        # 前车距离
        # ==========================================

        distance = selected_train.get(
            "distance_to_ahead"
        )

        if distance is None:

            distance_text = "无前车"

        else:

            distance_text = (
                f"{distance:.0f} m"
            )

        self.info_distance.setText(
            f"前车距离：{distance_text}"
        )

        # ==========================================
        # 制动距离
        # ==========================================

        braking = selected_train.get(
            "braking_distance",
            0
        )

        self.info_braking.setText(
            f"制动距离：{braking:.0f} m"
        )

    def clear_train_info(self):

        self.info_track.setText(
            "当前分区：--"
        )

        self.info_position.setText(
            "分区位置：--"
        )

        self.info_speed.setText(
            "当前速度：--"
        )

        self.info_target.setText(
            "目标速度：--"
        )

        self.info_code.setText(
            "当前码序：--"
        )

        self.info_line_speed.setText(
            "线路限速：--"
        )

        self.info_balise.setText(
            "最后应答器：--"
        )

        self.info_safety.setText(
            "安全状态：--"
        )

        self.info_distance.setText(
            "前车距离：--"
        )

        self.info_braking.setText(
            "制动距离：--"
        )

    # ==========================================
    # 站别与面板
    # ==========================================

    def get_simulation(self, role):
        """
        按站别取对应的TCC业务对象。
        """

        if role == "B":
            return self.simulation_b

        return self.simulation_a

    def get_direction_manager(self, role):
        """
        按站别取对应的改方管理器。
        """

        if role == "B":
            return self.direction_manager_b

        return self.direction_manager_a

    def get_tcc_code(self, role):
        """
        按站别取TCC编号。
        """

        return f"TCC_{role}"

    # ==========================================
    # 网络模式配置
    # ==========================================

    def apply_network_mode(self):
        """
        配置两站控制中心的按钮。

        A、B面板均为独立Server，分别监听不同端口。

        两侧各有独立的TCC与改方管理器，
        因此两站的改方按钮都可以使用。
        """

        # --------------------------
        # A站：Server
        # --------------------------

        self.panel_a.network_button.setEnabled(
            True
        )

        self.panel_a.network_button.setToolTip(
            "启动TCC_A服务器，监听127.0.0.1:9000"
        )

        self.panel_a.network_button.clicked.connect(
            lambda: self.start_network("A")
        )

        self.panel_a.disconnect_button.clicked.connect(
            lambda: self.disconnect_network("A")
        )

        self.panel_a.set_network_status(
            "通信状态：未启动"
        )

        self.panel_a.direction_button.setEnabled(
            True
        )

        self.panel_a.direction_button.setToolTip(
            "TCC_A申请把区间改为A站发车方向"
        )

        self.panel_a.direction_button.clicked.connect(
            lambda: self.request_direction_change("A")
        )

        # --------------------------
        # B站：Server
        # --------------------------

        self.panel_b.network_button.setEnabled(
            True
        )

        self.panel_b.network_button.setToolTip(
            "启动TCC_B服务器，监听127.0.0.1:9001"
        )

        self.panel_b.network_button.clicked.connect(
            lambda: self.start_network("B")
        )

        self.panel_b.disconnect_button.clicked.connect(
            lambda: self.disconnect_network("B")
        )

        self.panel_b.set_network_status(
            "通信状态：未启动"
        )

        self.panel_b.direction_button.setEnabled(
            True
        )

        self.panel_b.direction_button.setToolTip(
            "TCC_B申请把区间改为B站发车方向"
        )

        self.panel_b.direction_button.clicked.connect(
            lambda: self.request_direction_change("B")
        )

    # ==========================================
    # 控制权
    # ==========================================

    def get_panel_by_role(self, role):
        """
        按站别取控制面板。
        """

        if role == "B":
            return self.panel_b

        return self.panel_a

    def get_send_worker(self):
        """
        返回推送区间占用状态的通信端点。

        列车仿真始终挂在A侧，
        因此区间占用状态始终由TCC_A推送，
        B侧只接收并按自身自动闭塞重算码序。
        """

        return self.network_workers.get("A")

    def is_connected(self):
        """
        站间通信是否已经建立（任一端点已连通）。
        """

        for worker in self.network_workers.values():

            if worker.running:
                return True

        return False

    # ==========================================
    # 站间通信
    # ==========================================

    def start_network(self, role=None):
        """
        开启站间通信。

        A、B站分别创建服务器，使用独立端口避免冲突。
        """

        if role is None:
            return

        # 该站别已经启动过
        if role in self.network_workers:
            return

        panel = self.get_panel_by_role(role)

        host, port = self.network_endpoint(role)
        panel.set_network_status(f"通信状态：服务器已启动，监听{port}")

        worker = self.network_worker_class(role)(host, port)

        worker.connected.connect(
            lambda r=role: self.on_connected(r)
        )

        worker.disconnected.connect(
            lambda r=role: self.on_disconnected(r)
        )

        worker.message_received.connect(
            lambda m, r=role: self.on_message_received(m, r)
        )

        worker.error.connect(
            lambda text, r=role: self.on_network_error(r, text)
        )

        self.network_workers[role] = worker
        panel.network_button.setEnabled(False)
        panel.disconnect_button.setEnabled(True)
        worker.start()

    @staticmethod
    def network_worker_class(role):
        return ServerNetworkWorker

    @staticmethod
    def network_endpoint(role):
        return ("127.0.0.1", 9000 if role == "A" else 9001)

    def disconnect_network(self, role):
        worker = self.network_workers.pop(role, None)
        if worker is not None:
            worker.stop()
            worker.wait(1000)
        panel = self.get_panel_by_role(role)
        panel.network_button.setEnabled(True)
        panel.disconnect_button.setEnabled(False)
        panel.set_network_status(
            "通信状态：未启动"
        )

    def on_connected(self, role):

        self.get_panel_by_role(role).set_network_status(
            "通信状态：已连接"
        )
        self.get_panel_by_role(role).disconnect_button.setEnabled(True)

        # 连上以后立即同步一次
        self.send_track_status()
        self.send_signal_status(role)

    def on_disconnected(self, role):
        panel = self.get_panel_by_role(role)
        panel.set_network_status("通信状态：连接已断开")
        panel.network_button.setEnabled(True)
        panel.disconnect_button.setEnabled(False)
        worker = self.network_workers.get(role)
        if worker is not None and not worker.running:
            self.network_workers.pop(role, None)

    def on_network_error(self, role, error_message):

        self.get_panel_by_role(role).set_network_status(
            "通信状态：网络错误"
        )

        QMessageBox.warning(
            self,
            "网络错误",
            error_message
        )

    def on_message_received(self, message, role=None):

        message_type = message.get(
            "type"
        )

        data = message.get(
            "data",
            {}
        )

        # 报文一律作用在"收到它的那个TCC"上
        simulation = self.get_simulation(role)

        direction_manager = self.get_direction_manager(role)

        # ----------------------------------
        # 区间轨道状态：镜像对端区间
        # ----------------------------------

        if message_type == (
                MessageProtocol.TRACK_STATUS
        ):

            simulation.update_remote_tracks(
                data.get("tracks", []),
                data.get("train_position")
            )

            self.refresh_view()

        # ----------------------------------
        # 信号机状态
        # ----------------------------------

        elif message_type == (
                MessageProtocol.SIGNAL_STATUS
        ):

            simulation.update_remote_signal(
                data.get("signal"),
                data.get("status")
            )

            self.refresh_view()

        # ----------------------------------
        # 对端申请改方：本站判定后回复
        # ----------------------------------

        elif message_type == (
                MessageProtocol.DIRECTION_REQUEST
        ):

            target_direction = data.get(
                "target_direction"
            )

            approved, reason = (
                direction_manager
                .evaluate_request(
                    target_direction
                )
            )

            reply = direction_manager.create_reply(
                approved,
                target_direction,
                reason
            )

            # 从哪个端点收到就从哪个端点回复
            worker = self.network_workers.get(role)

            if worker is not None:

                worker.send_message(
                    reply
                )

            self.refresh_view()

        # ----------------------------------
        # 改方批准 / 拒绝
        # ----------------------------------

        elif message_type in (
                MessageProtocol.DIRECTION_APPROVE,
                MessageProtocol.DIRECTION_DENY
        ):

            text, success = (
                direction_manager
                .apply_reply(
                    message_type,
                    data
                )
            )

            self.refresh_view()

            if success:

                self.send_signal_status(role)

                QMessageBox.information(
                    self,
                    "区间改方成功",
                    "双方TCC已完成运行方向同步。"
                )

            else:

                QMessageBox.warning(
                    self,
                    "区间改方失败",
                    text
                )

    def send_track_status(self):
        """
        向TCC_B发送TCC_A掌握的区间轨道状态。

        列车仿真始终挂在A侧，
        因此区间占用状态由A侧单向推送，
        B侧收到后用自己的自动闭塞重算码序。
        """

        worker = self.get_send_worker()

        if worker is None or not worker.running:
            return

        tracks = []

        for track in (
                self.simulation_a
                .get_all_track_status()
        ):

            tracks.append({
                "code": track["track_code"],
                "status": track["status"]
            })

        message = MessageProtocol.create_message(
            MessageProtocol.TRACK_STATUS,
            self.get_tcc_code("A"),
            {
                "tracks": tracks,
                "train_position": (
                    self.simulation_a.train_position
                )
            }
        )

        worker.send_message(
            message
        )

    def send_signal_status(self, role):
        """
        由指定站别向对端发送自己的信号机显示。
        """

        worker = self.network_workers.get(role)

        if worker is None or not worker.running:
            return

        simulation = self.get_simulation(role)

        signal_code = simulation.signal.code

        message = MessageProtocol.create_message(
            MessageProtocol.SIGNAL_STATUS,
            self.get_tcc_code(role),
            {
                "signal": signal_code,
                "status": (
                    simulation.signal_states.get(
                        signal_code,
                        "红灯"
                    )
                )
            }
        )

        worker.send_message(
            message
        )

    def request_direction_change(self, role):
        """
        以指定站别的身份向邻站TCC申请区间改方。
        """

        worker = self.network_workers.get(role)

        if worker is None or not worker.running:

            QMessageBox.warning(
                self,
                "无法申请改方",
                "站间通信尚未建立。"
            )

            return

        direction_manager = self.get_direction_manager(role)

        message, reason = (
            direction_manager
            .create_request()
        )

        if message is None:

            if (
                    direction_manager.status
                    == DirectionManager.DENIED
            ):

                QMessageBox.warning(
                    self,
                    "无法改方",
                    "区间未清空。\n\n"
                    "请确认：\n"
                    "1. G01～G38全部空闲；\n"
                    "2. 区间内没有列车；\n"
                    "3. 出站信号机处于红灯。"
                )

            else:

                QMessageBox.information(
                    self,
                    "无需改方",
                    reason
                )

            self.refresh_view()

            return

        worker.send_message(
            message
        )

        self.refresh_view()

    # ==========================================
    # 退出
    # ==========================================

    def closeEvent(self, event):

        for worker in self.network_workers.values():

            worker.stop()

            worker.wait(1000)

        self.network_workers.clear()

        event.accept()
