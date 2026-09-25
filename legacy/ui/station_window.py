from services.simulation_service import SimulationService
from services.direction_manager import DirectionManager
from network.message_protocol import MessageProtocol
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QMessageBox,
)

from network.network_worker import (
    ClientNetworkWorker,
    ServerNetworkWorker
)
from ui.track_view import TrackView

class StationWindow(QMainWindow):
    """
    单个车站TCC主窗口。

    station_type = "A"
        A站，网络角色为Client

    station_type = "B"
        B站，网络角色为Server
    """

    def __init__(self, station_type):
        super().__init__()

        self.station_type = station_type
        self.simulation = SimulationService(
            station_type
        )

        self.network_worker = None
        self.remote_signal_code = None
        self.remote_signal_status = None

        self.init_station_info()

        # 区间改方管理器
        self.direction_manager = DirectionManager(
            self.simulation,
            self.tcc_code,
            station_type
        )

        self.init_ui()
        self.refresh_status()

    # ==================================================
    # 车站基本信息
    # ==================================================

    def init_station_info(self):

        if self.station_type == "A":

            self.station_name = "A站"
            self.tcc_code = "TCC_A"
            self.network_role = "Client"

        else:

            self.station_name = "B站"
            self.tcc_code = "TCC_B"
            self.network_role = "Server"

    # ==================================================
    # UI
    # ==================================================

    def init_ui(self):

        self.setWindowTitle(
            f"{self.station_name}列控中心 TCC"
        )

        self.resize(800, 600)

        central_widget = QWidget()

        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(
            central_widget
        )

        # -------------------------
        # 基本信息
        # -------------------------

        info_group = QGroupBox(
            "TCC基本信息"
        )

        info_layout = QVBoxLayout(
            info_group
        )

        self.station_label = QLabel(
            f"车站：{self.station_name}"
        )

        self.tcc_label = QLabel(
            f"TCC编号：{self.tcc_code}"
        )

        self.role_label = QLabel(
            f"网络角色：{self.network_role}"
        )

        info_layout.addWidget(
            self.station_label
        )

        info_layout.addWidget(
            self.tcc_label
        )

        info_layout.addWidget(
            self.role_label
        )

        # -------------------------
        # 通信区域
        # -------------------------

        network_group = QGroupBox(
            "站间通信"
        )

        network_layout = QVBoxLayout(
            network_group
        )

        self.connection_label = QLabel(
            "通信状态：未连接"
        )

        network_layout.addWidget(
            self.connection_label
        )

        if self.station_type == "A":

            self.network_button = QPushButton(
                "连接B站 TCC"
            )

        else:

            self.network_button = QPushButton(
                "启动TCC-B服务器"
            )

        network_layout.addWidget(
            self.network_button
        )

        # -------------------------
        # 区间状态
        # -------------------------

        section_group = QGroupBox(
            "区间状态"
        )

        section_layout = QVBoxLayout(
            section_group
        )
        # =========================
        # 闭塞分区状态显示
        # =========================

        track_grid = QGridLayout()

        # 表头
        track_grid.addWidget(
            QLabel("闭塞分区"),
            0,
            0
        )

        track_grid.addWidget(
            QLabel("占用状态"),
            0,
            1
        )

        track_grid.addWidget(
            QLabel("轨道编码"),
            0,
            2
        )

        # 保存8个分区对应的Label
        self.track_status_labels = {}
        self.track_code_labels = {}

        for i in range(1, 9):
            track_code = f"G{i:02d}"

            # 分区名称
            name_label = QLabel(
                track_code
            )

            # 空闲/占用
            status_label = QLabel(
                "空闲"
            )

            # L5/L3/L2/L/LU/U/HU
            code_label = QLabel(
                "-"
            )

            track_grid.addWidget(
                name_label,
                i,
                0
            )

            track_grid.addWidget(
                status_label,
                i,
                1
            )

            track_grid.addWidget(
                code_label,
                i,
                2
            )

            self.track_status_labels[
                track_code
            ] = status_label

            self.track_code_labels[
                track_code
            ] = code_label

        section_layout.addLayout(
            track_grid
        )
        self.track_view = TrackView()

        # 本站信号机状态
        self.signal_status_label = QLabel(
            "信号机：红灯"
        )

        self.train_position_label = QLabel(
            "列车位置：区间外"
        )

        # 区间运行方向
        self.direction_label = QLabel(
            "区间运行方向：A站 → B站"
        )

        # 改方状态：空闲/申请中/改方成功/区间未清空
        self.direction_status_label = QLabel(
            "改方状态：空闲"
        )

        section_layout.addWidget(
            self.track_view
        )

        section_layout.addWidget(
            self.signal_status_label
        )

        section_layout.addWidget(
            self.train_position_label
        )

        section_layout.addWidget(
            self.direction_label
        )

        section_layout.addWidget(
            self.direction_status_label
        )

        # -------------------------
        # 控制区域
        # -------------------------

        control_group = QGroupBox(
            "TCC控制"
        )

        control_layout = QHBoxLayout(
            control_group
        )

        # 开放信号按钮
        self.signal_button = QPushButton(
            "开放信号"
        )
        self.close_signal_button = QPushButton(
            "关闭信号"
        )

        # 区间改方按钮
        self.direction_button = QPushButton(
            "申请区间改方"
        )

        self.train_enter_button = QPushButton(
            "列车进入区间"
        )

        self.train_leave_button = QPushButton(
            "列车运行一步"
        )

        # 把4个按钮放进控制区域
        control_layout.addWidget(
            self.signal_button
        )
        control_layout.addWidget(
            self.close_signal_button
        )

        control_layout.addWidget(
            self.direction_button
        )

        control_layout.addWidget(
            self.train_enter_button
        )

        control_layout.addWidget(
            self.train_leave_button
        )

        # -------------------------
        # 加入主布局
        # -------------------------

        main_layout.addWidget(
            info_group
        )

        main_layout.addWidget(
            network_group
        )

        main_layout.addWidget(
            section_group
        )

        main_layout.addWidget(
            control_group
        )

        main_layout.addStretch()

        # 网络按钮
        self.network_button.clicked.connect(
            self.start_network
        )
        self.train_enter_button.clicked.connect(
            self.train_enter
        )

        self.train_leave_button.clicked.connect(
            self.train_leave
        )

        self.signal_button.clicked.connect(
            self.open_signal
        )
        self.close_signal_button.clicked.connect(
            self.close_signal
        )

        self.direction_button.clicked.connect(
            self.request_direction_change
        )

    # ==================================================
    # 网络启动
    # ==================================================

    def start_network(self):

        if self.network_worker is not None:
            return

        if self.station_type == "A":

            self.connection_label.setText(
                "通信状态：正在连接B站..."
            )

            self.network_worker = (
                ClientNetworkWorker()
            )

        else:

            self.connection_label.setText(
                "通信状态：等待A站连接..."
            )

            self.network_worker = (
                ServerNetworkWorker()
            )

        # -------------------------
        # 网络事件
        # -------------------------

        self.network_worker.connected.connect(
            self.on_connected
        )

        self.network_worker.disconnected.connect(
            self.on_disconnected
        )

        self.network_worker.message_received.connect(
            self.on_message_received
        )

        self.network_worker.error.connect(
            self.on_network_error
        )

        self.network_worker.start()

    # ==================================================
    # 网络事件
    # ==================================================

    def on_connected(self):

        self.connection_label.setText(
            "通信状态：已连接"
        )

    def on_disconnected(self):

        self.connection_label.setText(
            "通信状态：连接已断开"
        )

    def on_network_error(self, error_message):

        self.connection_label.setText(
            "通信状态：网络错误"
        )

        QMessageBox.warning(
            self,
            "网络错误",
            error_message
        )

    def on_message_received(self, message):

        print(
            f"{self.tcc_code}收到消息：",
            message
        )

        message_type = message.get(
            "type"
        )

        # ==================================
        # 轨道状态消息
        # ==================================

        if message_type == MessageProtocol.TRACK_STATUS:

            data = message.get(
                "data",
                {}
            )

            tracks = data.get(
                "tracks",
                []
            )

            train_position = data.get(
                "train_position"
            )

            self.simulation.update_remote_tracks(
                tracks,
                train_position
            )

            self.refresh_status()
        elif message_type == MessageProtocol.SIGNAL_STATUS:

            data = message.get(
                "data",
                {}
            )

            signal_code = data.get(
                "signal"
            )

            signal_status = data.get(
                "status"
            )

            self.simulation.update_remote_signal(
                signal_code,
                signal_status
            )

            self.refresh_status()
        elif message_type == MessageProtocol.SIGNAL_STATUS:

            data = message.get(
                "data",
                {}
            )

            self.remote_signal_code = data.get(
                "signal"
            )

            self.remote_signal_status = data.get(
                "status"
            )

            print(
                f"{self.tcc_code}获知对端信号状态："
                f"{self.remote_signal_code} = "
                f"{self.remote_signal_status}"
            )
        elif message_type == MessageProtocol.DIRECTION_REQUEST:

            data = message.get(
                "data",
                {}
            )

            target_direction = data.get(
                "target_direction"
            )

            self.handle_direction_request(
                target_direction
            )
        elif message_type in (
                MessageProtocol.DIRECTION_APPROVE,
                MessageProtocol.DIRECTION_DENY
        ):

            data = message.get(
                "data",
                {}
            )

            text, success = (
                self.direction_manager
                .apply_reply(
                    message_type,
                    data
                )
            )

            self.refresh_status()

            if success:

                self.send_signal_status()

                self.connection_label.setText(
                    "通信状态：已连接"
                )

                QMessageBox.information(
                    self,
                    "区间改方成功",
                    "双方TCC已完成运行方向同步。"
                )

            else:

                self.connection_label.setText(
                    "通信状态：已连接"
                )

                QMessageBox.warning(
                    self,
                    "区间改方失败",
                    text
                )

        elif message_type == MessageProtocol.DIRECTION_CONFIRM:

            data = message.get(
                "data",
                {}
            )

            accepted = data.get(
                "accepted",
                False
            )

            target_direction = data.get(
                "target_direction"
            )

            if accepted:

                self.simulation.set_direction(
                    target_direction
                )

                self.refresh_status()
                self.send_signal_status()

                self.connection_label.setText(
                    "通信状态：已连接"
                )

                QMessageBox.information(
                    self,
                    "区间改方成功",
                    "双方TCC已完成运行方向同步。"
                )

            else:

                reason = data.get(
                    "reason",
                    "对端TCC拒绝改方"
                )

                self.connection_label.setText(
                    "通信状态：已连接"
                )

                QMessageBox.warning(
                    self,
                    "区间改方失败",
                    reason
                )

    # ==================================================
    # 关闭窗口
    # ==================================================

    def closeEvent(self, event):

        if self.network_worker is not None:
            self.network_worker.stop()

            self.network_worker.wait(1000)

        event.accept()

    def train_enter(self):
        """
        模拟列车从当前运行方向的起点进入区间。
        """

        result = self.simulation.train_enter_track()

        if not result:
            QMessageBox.warning(
                self,
                "列车无法进入",
                "当前已有列车在区间内，或入口闭塞分区被占用。"
            )
            return

        # 刷新本站界面
        self.refresh_status()
        self.send_track_status()
        self.send_signal_status()

        QMessageBox.information(
            self,
            "列车进入区间",
            f"列车已进入 {self.simulation.train_position}"
        )

    def open_signal(self):
        """
        尝试开放本站信号机。
        """

        success = self.simulation.open_signal()

        self.refresh_status()

        if not success:

            status = self.simulation.get_system_status()

            if status["track_status"] == "占用":

                reason = (
                    "G01区间当前处于占用状态，"
                    "禁止开放信号。"
                )

            else:

                reason = (
                    "当前区间运行方向不允许"
                    "本站开放该信号机。"
                )

            QMessageBox.warning(
                self,
                "信号开放失败",
                reason
            )

            return

        # 开放成功后，将信号状态发送给另一TCC
        self.send_signal_status()

    def close_signal(self):
        """
        主动关闭本站信号机。
        """

        # 1. 修改本地信号状态
        self.simulation.close_signal()

        # 2. 刷新本地界面
        self.refresh_status()

        # 3. 把新的信号状态告诉邻站TCC
        self.send_signal_status()

    def train_leave(self):
        """
        模拟列车沿当前运行方向前进一步。
        """

        result = self.simulation.move_train_forward()

        # -------------------------
        # 当前没有列车
        # -------------------------

        if result == "NO_TRAIN":
            QMessageBox.warning(
                self,
                "无法运行",
                "当前区间内没有列车。"
            )

            return

        # -------------------------
        # 下一闭塞分区被占用
        # -------------------------

        if result == "BLOCKED":
            QMessageBox.warning(
                self,
                "前方闭塞",
                "前方闭塞分区处于占用状态，列车不能继续运行。"
            )

            return

        # -------------------------
        # 正常向前运行
        # -------------------------

        if result == "MOVED":
            self.refresh_status()

            self.send_track_status()

            return

        # -------------------------
        # 驶出区间
        # -------------------------

        if result == "ARRIVED":
            self.refresh_status()

            self.send_track_status()

            QMessageBox.information(
                self,
                "列车到达",
                "列车已驶出A站—B站区间。"
            )

    def refresh_status(self):

        status = (
            self.simulation.get_system_status()
        )

        # =========================
        # 1. 刷新所有闭塞分区
        # =========================

        track_list = (
            self.simulation.get_all_track_status()
        )

        for track in track_list:
            track_code = track["track_code"]

            track_status = track["status"]

            code = track["signal_code"]

            self.track_status_labels[
                track_code
            ].setText(
                track_status
            )

            self.track_code_labels[
                track_code
            ].setText(
                code
            )

        # =========================
        # 刷新列车位置
        # =========================

        train_position = (
            self.simulation.train_position
        )

        if train_position is None:

            train_text = "区间外"

        else:

            train_text = train_position

        self.train_position_label.setText(
            f"列车位置：{train_text}"
        )

        # =========================
        # 2. 刷新信号机
        # =========================

        self.signal_status_label.setText(
            f'{status["signal_code"]}信号机：'
            f'{status["signal_status"]}'
        )

        # =========================
        # 3. 刷新区间方向
        # =========================

        direction = status[
            "direction"
        ]

        if direction == "A_TO_B":

            direction_text = "A站 → B站"

        else:

            direction_text = "B站 → A站"

        self.direction_label.setText(
            f"区间运行方向：{direction_text}"
        )

        # 改方状态：空闲/申请中/改方成功/区间未清空
        self.direction_status_label.setText(
            f"改方状态："
            f"{self.direction_manager.status}"
        )

        # =========================
        # 根据运行方向设置列车控制权限
        # =========================

        can_control = (
            self.simulation.can_control_train()
        )

        self.train_enter_button.setEnabled(
            can_control
        )

        self.train_leave_button.setEnabled(
            can_control
        )

        # =========================
        # 刷新线路可视化
        # =========================

        self.track_view.set_state(
            tracks=track_list,
            train_position=self.simulation.train_position,
            direction=self.simulation.get_direction(),

            signal_a=self.simulation.signal_states.get(
                "S01",
                "红灯"
            ),

            signal_b=self.simulation.signal_states.get(
                "S02",
                "红灯"
            )
        )

    def send_signal_status(self):
        """
        向邻站TCC发送本站信号机状态。
        """

        if (
                self.network_worker is None
                or not self.network_worker.running
        ):
            return

        data = {
            "signal_code":
                self.simulation.signal.code,

            "signal_status":
                self.simulation.signal.get_aspect()
        }

        message = (
            MessageProtocol.create_message(
                MessageProtocol.SIGNAL_STATUS,
                self.tcc_code,
                data
            )
        )

        self.network_worker.send_message(
            message
        )

    def send_track_status(self):
        """
        向邻站TCC发送整个区间的轨道状态。
        """

        if (
                self.network_worker is None
                or not self.network_worker.running
        ):
            return

        # 获取G01～G08全部状态
        track_list = (
            self.simulation.get_all_track_status()
        )

        # 网络报文只发送基础状态
        tracks = []

        for track in track_list:
            tracks.append({
                "code": track["track_code"],
                "status": track["status"]
            })

        data = {
            "tracks": tracks,
            "train_position":
                self.simulation.train_position
        }

        message = (
            MessageProtocol.create_message(
                MessageProtocol.TRACK_STATUS,
                self.tcc_code,
                data
            )
        )

        self.network_worker.send_message(
            message
        )

    def send_signal_status(self):
        """
        将本站信号机状态发送给另一TCC。
        """

        if self.network_worker is None:
            return

        if not self.network_worker.running:
            return

        status = self.simulation.get_system_status()

        message = MessageProtocol.create_message(
            MessageProtocol.SIGNAL_STATUS,
            self.tcc_code,
            {
                "signal": status["signal_code"],
                "status": status["signal_status"]
            }
        )

        self.network_worker.send_message(
            message
        )

    def get_requested_direction(self):
        """
        根据本站确定希望申请的运行方向。
        """

        if self.station_type == "A":
            return "A_TO_B"

        return "B_TO_A"

    def request_direction_change(self):
        """
        向邻站TCC申请区间改方。
        """

        # --------------------------
        # 1. 必须已经建立通信
        # --------------------------

        if (
                self.network_worker is None
                or not self.network_worker.running
        ):
            QMessageBox.warning(
                self,
                "无法申请改方",
                "站间通信尚未建立。"
            )

            return

        # --------------------------
        # 2. 由改方管理器判定并构造申请报文
        # --------------------------

        message, reason = (
            self.direction_manager
            .create_request()
        )

        if message is None:

            if (
                    self.direction_manager.status
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

            self.refresh_status()

            return

        # --------------------------
        # 3. 发送改方申请
        # --------------------------

        self.network_worker.send_message(
            message
        )

        self.connection_label.setText(
            "通信状态：已连接（等待改方确认）"
        )

        self.refresh_status()

    def handle_direction_request(self, target_direction):
        """
        处理邻站发送的区间改方请求。
        """

        # --------------------------
        # 由改方管理器做安全检查
        # --------------------------

        approved, reason = (
            self.direction_manager
            .evaluate_request(
                target_direction
            )
        )

        # --------------------------
        # 回复批准或拒绝报文
        # --------------------------

        reply = self.direction_manager.create_reply(
            approved,
            target_direction,
            reason
        )

        self.network_worker.send_message(
            reply
        )

        self.refresh_status()

        if approved:
            self.send_signal_status()
