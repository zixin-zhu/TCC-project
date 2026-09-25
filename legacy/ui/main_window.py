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
    QMessageBox
)

from services.simulation_service import SimulationService
from services.train_service import TrainService
from services.simulation_engine import SimulationEngine
from services.direction_manager import DirectionManager

from network.message_protocol import MessageProtocol
from network.network_worker import (
    ClientNetworkWorker,
    ServerNetworkWorker
)

from ui.station_panel import StationPanel
from ui.simulation_view import SimulationView


class MainWindow(QMainWindow):
    """
    单窗口双TCC架构。

    窗口里同时存在两个相互独立的TCC对象：

    TCC_A（simulation_a）
        通信角色 Client，信号机 S01，自有8个闭塞分区

    TCC_B（simulation_b）
        通信角色 Server，信号机 S02，自有8个闭塞分区

    两者通过本机TCP（127.0.0.1）互联，
    各自用自己的自动闭塞算法计算码序。

    列车仿真（TrainService）挂在A侧，
    B侧通过报文镜像区间占用后自行重算。
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "高铁车站列控中心 TCC 功能仿真系统"
        )

        self.resize(
            1280,
            820
        )

        # ==========================
        # 双TCC后台服务
        # ==========================

        # A站TCC，通信角色Client
        self.simulation_a = SimulationService("A")

        # B站TCC，通信角色Server
        self.simulation_b = SimulationService("B")

        # 列车仿真始终挂在A侧
        self.train_service = TrainService(
            self.simulation_a
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

        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(
            central
        )

        # ==========================
        # A/B站控制中心
        # ==========================

        station_layout = QHBoxLayout()

        self.panel_a = StationPanel("A")
        self.panel_b = StationPanel("B")

        station_layout.addWidget(
            self.panel_a
        )

        station_layout.addWidget(
            self.panel_b
        )

        main_layout.addLayout(
            station_layout
        )

        # ==========================
        # 动态线路
        # ==========================

        self.simulation_view = (
            SimulationView()
        )

        main_layout.addWidget(
            self.simulation_view,
            1
        )

        # ==========================================
        # 列车实时状态面板
        # ==========================================

        train_info_group = QGroupBox(
            "列车实时运行状态"
        )

        train_info_layout = QGridLayout(
            train_info_group
        )

        # 列车选择
        train_info_layout.addWidget(
            QLabel("查看列车："),
            0,
            0
        )

        self.train_selector = QComboBox()

        train_info_layout.addWidget(
            self.train_selector,
            0,
            1
        )

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

        train_info_layout.addWidget(
            self.info_track,
            1,
            0
        )

        train_info_layout.addWidget(
            self.info_position,
            1,
            1
        )

        train_info_layout.addWidget(
            self.info_speed,
            1,
            2
        )

        train_info_layout.addWidget(
            self.info_target,
            1,
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

        train_info_layout.addWidget(
            self.info_code,
            2,
            0
        )

        train_info_layout.addWidget(
            self.info_line_speed,
            2,
            1
        )

        train_info_layout.addWidget(
            self.info_balise,
            2,
            2
        )

        train_info_layout.addWidget(
            self.info_safety,
            2,
            3
        )

        # 第三行
        self.info_distance = QLabel(
            "前车距离：--"
        )

        self.info_braking = QLabel(
            "制动距离：--"
        )

        train_info_layout.addWidget(
            self.info_distance,
            3,
            0
        )

        train_info_layout.addWidget(
            self.info_braking,
            3,
            1
        )

        main_layout.addWidget(
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
            QLabel("仿真倍速：")
        )

        control_layout.addWidget(
            self.speed_combo
        )

        control_layout.addStretch()

        control_layout.addWidget(
            self.running_label
        )

        control_layout.addWidget(
            self.queue_label
        )

        control_layout.addWidget(
            self.time_label
        )

        main_layout.addLayout(
            control_layout
        )

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

        self.speed_combo.currentTextChanged.connect(
            self.change_speed
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

        trains = (
            self.train_service.get_all_train_status()
        )

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
            signal_b=signal_b
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

        A面板：TCC_A，通信角色Client，可连接服务器
        B面板：TCC_B，通信角色Server，可开启服务器

        两侧各有独立的TCC与改方管理器，
        因此两站的改方按钮都可以使用。
        """

        # --------------------------
        # A站：Client
        # --------------------------

        self.panel_a.network_button.setEnabled(
            True
        )

        self.panel_a.network_button.setToolTip(
            "以TCC_A的Client身份连接TCC_B服务器"
        )

        self.panel_a.network_button.clicked.connect(
            lambda: self.start_network("A")
        )

        self.panel_a.set_network_status(
            "通信状态：未连接"
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
            "以TCC_B的Server身份开启服务器"
        )

        self.panel_b.network_button.clicked.connect(
            lambda: self.start_network("B")
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

        A站角色创建客户端连接TCC_B，
        B站角色创建服务器等待TCC_A连接。

        两个端点在同一个窗口里通过本机TCP互联。
        """

        if role is None:
            return

        # 该站别已经启动过
        if role in self.network_workers:
            return

        panel = self.get_panel_by_role(role)

        if role == "A":

            panel.set_network_status(
                "通信状态：联网模式（正在连接B站）"
            )

            worker = ClientNetworkWorker()

        else:

            panel.set_network_status(
                "通信状态：联网模式（等待A站连接）"
            )

            worker = ServerNetworkWorker()

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

        worker.start()

        self.network_workers[role] = worker

    def on_connected(self, role):

        self.get_panel_by_role(role).set_network_status(
            "通信状态：已连接"
        )

        # 连上以后立即同步一次
        self.send_track_status()
        self.send_signal_status(role)

    def on_disconnected(self, role):

        self.get_panel_by_role(role).set_network_status(
            "通信状态：连接已断开"
        )

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
                    "1. G01～G08全部空闲；\n"
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