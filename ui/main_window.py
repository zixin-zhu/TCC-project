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
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from PyQt5.QtGui import QColor, QPalette

from services.simulation_service import SimulationService
from services.train_service import TrainService
from services.simulation_engine import SimulationEngine
from services.direction_manager import DirectionManager
from services.temporary_speed_service import TemporarySpeedService
from services.route_service import RouteService
from services.operation_policy import OperationPolicy, OperationRuleError
from models.route import RouteState, RouteType
from models.train import Train

from network.message_protocol import MessageProtocol
from network.network_worker import (
    ClientNetworkWorker,
    ServerNetworkWorker
)

from ui.station_panel import StationPanel
from ui.tcc_overview import HorizontalWheelScrollArea, TccOverviewWidget
from ui.theme import APP_STYLESHEET


class ComboHoverDelegate(QStyledItemDelegate):
    """稳定绘制下拉项的悬停与选中反馈。"""

    def paint(self, painter, option, index):
        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)
        if styled_option.state & QStyle.State_MouseOver:
            styled_option.state |= QStyle.State_Selected
        styled_option.palette.setColor(
            QPalette.Highlight,
            QColor("#dceefe"),
        )
        styled_option.palette.setColor(
            QPalette.HighlightedText,
            QColor("#1d2a36"),
        )
        super().paint(painter, styled_option, index)


class MainWindow(QMainWindow):
    """
    单窗口双TCC架构。

    窗口里同时存在两个相互独立的TCC对象：

    TCC_A（simulation_a）
        信号机 S01，自有38个轨道区段

    TCC_B（simulation_b）
        信号机 S02，自有38个轨道区段

    两站完全对等：先启动者内部作为Server监听9000，
    后启动者内部作为Client连接9000，界面不显示角色。

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
        self.setMinimumSize(1600, 760)
        self.setStyleSheet(APP_STYLESHEET)

        # ==========================
        # 双TCC后台服务
        # ==========================

        self.route_service = RouteService()

        # A站TCC
        self.simulation_a = SimulationService("A", self.route_service)

        # B站TCC
        self.simulation_b = SimulationService("B", self.route_service)

        # 列车仿真始终挂在A侧
        self.train_service = TrainService(
            self.simulation_a,
            self.route_service,
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
            "A",
            self.route_service,
        )

        self.direction_manager_b = DirectionManager(
            self.simulation_b,
            "TCC_B",
            "B",
            self.route_service,
        )

        # 站间通信端点：{站别: worker}
        self.network_workers = {}
        self.network_modes = {}
        self.network_server_station = None
        self.connected_stations = set()
        self._network_resetting = False

        # 待发列车的界面草稿独立保存；添加列车时不写入接发方式。
        self._train_control_drafts = {}

        # 站间同步节拍计数
        self.network_tick = 0

        self.init_ui()

        self.apply_network_mode()

        self.refresh_view()

        for combo in self.findChildren(QComboBox):
            self._configure_combo_popup(combo)

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
        self.panel_a.direction_button.setText("A站改方")
        self.panel_b.direction_button.setText("B站改方")
        self.panel_a.direction_button.setToolTip("A站申请区间改方")
        self.panel_b.direction_button.setToolTip("B站申请区间改方")
        direction_group_layout.addWidget(self.panel_a.direction_button)
        direction_group_layout.addWidget(self.panel_b.direction_button)

        route_group = QGroupBox("进路建立")
        route_group.setObjectName("route_management_area")
        route_group.setMinimumWidth(400)
        route_layout = QVBoxLayout(route_group)
        route_layout.setContentsMargins(6, 8, 6, 8)
        route_layout.setSpacing(5)
        route_primary_layout = QGridLayout()
        route_primary_layout.setHorizontalSpacing(0)

        self.route_station_label = QLabel("车站：")
        self.route_station_label.setFixedWidth(52)
        route_primary_layout.addWidget(self.route_station_label, 0, 0)

        self.route_station_combo = QComboBox()
        self.route_station_combo.setObjectName("route_station")
        self.route_station_combo.addItems(["A站", "B站"])
        self.route_station_combo.setToolTip("选择需要办理进路的车站")
        self.route_station_combo.setMinimumWidth(54)
        self.route_station_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.route_station_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        route_primary_layout.addWidget(self.route_station_combo, 0, 1)

        self.route_type_label = QLabel("进路类型：")
        self.route_type_label.setFixedWidth(86)
        route_primary_layout.addWidget(self.route_type_label, 0, 2)

        self.route_type_combo = QComboBox()
        self.route_type_combo.setObjectName("route_type")
        self.route_type_combo.addItems(
            ["正线接车", "侧线接车", "正线发车", "侧线发车"]
        )
        self.route_type_combo.setToolTip("选择接车或发车进路类型")
        self.route_type_combo.setMinimumWidth(94)
        self.route_type_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.route_type_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        route_primary_layout.addWidget(self.route_type_combo, 0, 3)

        self.route_establish_button = QPushButton("建立进路")
        self.route_establish_button.setObjectName("route_establish_button")
        self.route_establish_button.setToolTip("建立所选车站进路")
        self.route_establish_button.setFixedWidth(82)
        self.route_establish_button.setStyleSheet("padding: 0 5px;")
        route_primary_layout.addWidget(self.route_establish_button, 0, 4)
        route_primary_layout.setColumnStretch(1, 1)
        route_primary_layout.setColumnStretch(3, 2)
        route_layout.addLayout(route_primary_layout)

        active_route_layout = QGridLayout()
        active_route_layout.setHorizontalSpacing(0)

        self.active_route_label = QLabel("已建立进路：")
        self.active_route_label.setFixedWidth(104)
        active_route_layout.addWidget(self.active_route_label, 0, 0)

        self.active_route_combo = QComboBox()
        self.active_route_combo.setObjectName("active_route")
        self.active_route_combo.setToolTip("选择需要取消的已建立进路")
        self.active_route_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        self.active_route_combo.setMinimumWidth(130)
        self.active_route_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.active_route_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.active_route_combo.setMinimumContentsLength(8)
        active_route_layout.addWidget(self.active_route_combo, 0, 1)

        self.route_cancel_button = QPushButton("取消选中进路")
        self.route_cancel_button.setObjectName("route_cancel_button")
        self.route_cancel_button.setToolTip("取消列车尚未进入的所选进路")
        self.route_cancel_button.setFixedWidth(116)
        self.route_cancel_button.setStyleSheet("padding: 0 5px;")
        active_route_layout.addWidget(self.route_cancel_button, 0, 2)
        active_route_layout.setColumnStretch(1, 1)
        route_layout.addLayout(active_route_layout)

        equipment_group = QGroupBox(
            "临时限速"
        )
        equipment_group.setObjectName("temporary_speed_area")
        equipment_group.setMinimumWidth(550)
        equipment_layout = QVBoxLayout(equipment_group)
        equipment_layout.setContentsMargins(6, 8, 6, 8)
        equipment_layout.setSpacing(5)
        tsr_primary_layout = QGridLayout()
        tsr_primary_layout.setHorizontalSpacing(0)

        self.tsr_start_label = QLabel("起始区段：")
        self.tsr_start_label.setFixedWidth(86)
        tsr_primary_layout.addWidget(self.tsr_start_label, 0, 0)
        self.tsr_start_combo = QComboBox()
        self.tsr_start_combo.setObjectName("tsr_start_section")
        self.tsr_start_combo.addItems([f"G{i:02d}" for i in range(1, 39)])
        self.tsr_start_combo.setMinimumWidth(59)
        self.tsr_start_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.tsr_start_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        self.tsr_start_combo.setToolTip("临时限速起始区段")
        tsr_primary_layout.addWidget(self.tsr_start_combo, 0, 1)

        self.tsr_end_label = QLabel("终止区段：")
        self.tsr_end_label.setFixedWidth(86)
        tsr_primary_layout.addWidget(self.tsr_end_label, 0, 2)
        self.tsr_end_combo = QComboBox()
        self.tsr_end_combo.setObjectName("tsr_end_section")
        self.tsr_end_combo.addItems([f"G{i:02d}" for i in range(1, 39)])
        self.tsr_end_combo.setMinimumWidth(59)
        self.tsr_end_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.tsr_end_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        self.tsr_end_combo.setToolTip("临时限速终止区段")
        tsr_primary_layout.addWidget(self.tsr_end_combo, 0, 3)

        self.tsr_speed_label = QLabel("限速：")
        self.tsr_speed_label.setFixedWidth(52)
        tsr_primary_layout.addWidget(self.tsr_speed_label, 0, 4)
        self.tsr_speed_combo = QComboBox()
        self.tsr_speed_combo.setObjectName("tsr_speed")
        self.tsr_speed_combo.addItems(["45 km/h", "80 km/h", "120 km/h", "160 km/h", "200 km/h", "250 km/h"])
        self.tsr_speed_combo.setMinimumWidth(98)
        self.tsr_speed_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.tsr_speed_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        self.tsr_speed_combo.setToolTip("临时限速值")
        tsr_primary_layout.addWidget(self.tsr_speed_combo, 0, 5)

        self.tsr_apply_button = QPushButton("设置限速")
        self.tsr_apply_button.setObjectName("tsr_apply_button")
        self.tsr_apply_button.setToolTip("设置所选区段范围的临时限速")
        self.tsr_apply_button.setFixedWidth(82)
        self.tsr_apply_button.setStyleSheet("padding: 0 5px;")
        tsr_primary_layout.addWidget(self.tsr_apply_button, 0, 6)
        tsr_primary_layout.setColumnStretch(1, 1)
        tsr_primary_layout.setColumnStretch(3, 1)
        tsr_primary_layout.setColumnStretch(5, 2)
        equipment_layout.addLayout(tsr_primary_layout)

        active_tsr_layout = QGridLayout()
        active_tsr_layout.setHorizontalSpacing(0)

        self.active_tsr_label = QLabel("已生效限速：")
        self.active_tsr_label.setFixedWidth(104)
        active_tsr_layout.addWidget(self.active_tsr_label, 0, 0)
        self.active_tsr_combo = QComboBox()
        self.active_tsr_combo.setObjectName("active_tsr")
        self.active_tsr_combo.setMinimumWidth(150)
        self.active_tsr_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.active_tsr_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.active_tsr_combo.setMinimumContentsLength(12)
        self.active_tsr_combo.setStyleSheet(
            "padding-left: 4px; padding-right: 3px;"
        )
        active_tsr_layout.addWidget(self.active_tsr_combo, 0, 1)

        self.tsr_cancel_button = QPushButton("取消选中限速")
        self.tsr_cancel_button.setObjectName("tsr_cancel_button")
        self.tsr_cancel_button.setToolTip("取消当前选中的临时限速")
        self.tsr_cancel_button.setFixedWidth(116)
        self.tsr_cancel_button.setStyleSheet("padding: 0 5px;")
        active_tsr_layout.addWidget(self.tsr_cancel_button, 0, 2)
        active_tsr_layout.setColumnStretch(1, 1)
        equipment_layout.addLayout(active_tsr_layout)

        self.operation_top_layout.addWidget(direction_group, 1)
        self.operation_top_layout.addWidget(route_group, 4)
        self.operation_top_layout.addWidget(equipment_group, 5)
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
        self.train_selector_layout.addSpacing(10)

        self.train_selector_layout.addWidget(QLabel("最大速度："))
        self.max_speed_combo = QComboBox()
        self.max_speed_combo.setObjectName("train_max_speed")
        self.max_speed_combo.addItems(
            [f"{speed} km/h" for speed in Train.ALLOWED_MAX_SPEEDS]
        )
        self.max_speed_combo.setCurrentText("120 km/h")
        self.max_speed_combo.setMinimumWidth(105)
        self.train_selector_layout.addWidget(self.max_speed_combo)
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
            "▶ 发车"
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
                "5×",
                "10×",
                "20×"
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
            self.dispatch_selected_train
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

        self.train_selector.currentTextChanged.connect(
            self.on_selected_train_changed
        )
        self.departure_mode_combo.currentTextChanged.connect(
            self.remember_selected_train_draft
        )
        self.arrival_mode_combo.currentTextChanged.connect(
            self.remember_selected_train_draft
        )
        self.max_speed_combo.currentTextChanged.connect(
            self.change_selected_train_max_speed
        )

        self.tsr_apply_button.clicked.connect(
            self.apply_temporary_speed_restriction
        )

        self.tsr_cancel_button.clicked.connect(
            self.cancel_temporary_speed_restriction
        )

        self.active_tsr_combo.currentIndexChanged.connect(
            lambda: self.refresh_control_states()
        )

        self.route_establish_button.clicked.connect(
            self.establish_selected_route
        )

        self.route_cancel_button.clicked.connect(
            self.cancel_selected_route
        )

        self.active_route_combo.currentIndexChanged.connect(
            self._sync_route_cancel_button
        )

        self.simulation_view.balise_clicked.connect(
            self.show_balise_information
        )

        self.refresh_route_controls()

    @staticmethod
    def _configure_combo_popup(combo):
        view = combo.view()
        view.setMouseTracking(True)

        palette = view.palette()
        for group in (
            QPalette.Active,
            QPalette.Inactive,
            QPalette.Disabled,
        ):
            palette.setColor(group, QPalette.Highlight, QColor("#dceefe"))
            palette.setColor(
                group,
                QPalette.HighlightedText,
                QColor("#1d2a36"),
            )
        view.setPalette(palette)
        combo._hover_delegate = ComboHoverDelegate(view)
        view.setItemDelegate(combo._hover_delegate)

    # ==============================
    # 添加待发列车
    # ==============================

    def add_waiting_train(self):

        if not self.require_communication("添加列车失败"):
            return

        train = self.train_service.add_waiting_train()

        print(
            f"{train.train_id} 已加入待发队列"
        )

        self.refresh_view()

    # ==============================
    # 发出当前选中的一辆列车
    # ==============================

    def dispatch_selected_train(self):

        if not self.require_communication("列车发车失败"):
            return

        train_id = self.train_selector.currentText()
        train = self.train_service.trains.get(train_id)
        if train is None:
            self.show_operation_error(
                "列车发车失败",
                OperationRuleError(
                    "没有选中需要发出的列车",
                    "“查看列车”中未选中有效列车。",
                    "请先添加待发列车，并在下拉框中选中目标列车。",
                ),
            )
            return

        departure_mode = (
            "MAIN"
            if self.departure_mode_combo.currentText() == "正线发车"
            else "SIDE"
        )
        arrival_mode = (
            "MAIN"
            if self.arrival_mode_combo.currentText() == "正线接车"
            else "SIDE"
        )
        max_speed = int(self.max_speed_combo.currentText().split()[0])

        was_globally_paused = self.train_service.globally_paused
        try:
            self.train_service.dispatch_selected_train(
                train_id,
                departure_mode,
                arrival_mode,
                max_speed,
            )
        except (OperationRuleError, ValueError) as error:
            self.show_operation_error("列车发车失败", error)
            self.refresh_control_states()
            return

        # 暂停期间发出新车时，恢复全部已发车列车和全局时钟。
        if was_globally_paused:
            self.train_service.resume_all()
        self.engine.start()
        self.refresh_route_controls()
        self.refresh_view()

    def start_simulation(self):
        """兼容旧调用名称；按钮语义已经统一为发车。"""
        self.dispatch_selected_train()

    # ==============================
    # 暂停
    # ==============================

    def pause_simulation(self):

        if not self.require_communication("暂停仿真失败"):
            return

        running = any(
            train.status == "RUNNING"
            for train in self.train_service.trains.values()
        )
        stopped = any(
            train.status == "STOPPED"
            for train in self.train_service.trains.values()
        )

        if not (running or stopped):
            self.show_operation_error(
                "仿真暂停失败",
                OperationRuleError(
                    "当前没有可暂停或继续的列车",
                    "运行和暂停中的列车数量均为 0。",
                    "请先发出一辆待发列车后再使用暂停或继续。",
                ),
            )
        elif self.engine.timer.isActive():
            self.train_service.pause_all()
            self.engine.pause()
        elif self.train_service.globally_paused and stopped:
            self.train_service.resume_all()
            self.engine.start()
        else:
            self.show_operation_error(
                "仿真暂停失败",
                OperationRuleError(
                    "当前没有可暂停或继续的列车",
                    "仿真未处于可继续状态。",
                    "请先发出一辆待发列车后再使用暂停或继续。",
                ),
            )
        self.refresh_view()

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

    def remember_selected_train_draft(self, _text=None):
        train_id = self.train_selector.currentText()
        train = self.train_service.trains.get(train_id)
        if train is None or train.status != "WAITING":
            return
        self._train_control_drafts[train_id] = {
            "departure": self.departure_mode_combo.currentText(),
            "arrival": self.arrival_mode_combo.currentText(),
            "max_speed": self.max_speed_combo.currentText(),
        }

    def change_selected_train_max_speed(self, text):
        train_id = self.train_selector.currentText()
        train = self.train_service.trains.get(train_id)
        if train is None or not text:
            return
        if train.status == "ARRIVED":
            return
        try:
            speed = int(text.split()[0])
            train.set_max_speed(speed)
            if train.current_track is not None:
                self.train_service.update_train_speed_limit(train)
        except (ValueError, IndexError) as error:
            self.show_operation_error("最大速度设置失败", error)
            return
        self.remember_selected_train_draft()
        self.refresh_train_info(self.train_service.get_all_train_status())

    def apply_temporary_speed_restriction(self):
        if not self.require_communication("限速设置失败"):
            return
        try:
            speed = int(self.tsr_speed_combo.currentText().split()[0])
            self.temporary_speed_service.set_restriction(
                self.tsr_start_combo.currentText(),
                self.tsr_end_combo.currentText(),
                speed,
            )
        except ValueError as error:
            self.show_operation_error("限速设置失败", error)
            return
        self.refresh_temporary_speed_controls()
        self.refresh_view()

    def cancel_temporary_speed_restriction(self):
        if not self.require_communication("限速取消失败"):
            return
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
        self.refresh_control_states()

    def establish_selected_route(self):
        if not self.require_communication("进路建立失败"):
            return
        route_types = {
            "正线接车": RouteType.MAIN_RECEIVE,
            "侧线接车": RouteType.SIDE_RECEIVE,
            "正线发车": RouteType.MAIN_DEPART,
            "侧线发车": RouteType.SIDE_DEPART,
        }
        station = self.route_station_combo.currentText().replace("站", "")
        route_type = route_types[self.route_type_combo.currentText()]
        try:
            OperationPolicy.validate_route_request(
                self.simulation_a.get_direction(),
                station,
                route_type,
            )
            self.route_service.establish_route(station, route_type)
        except (OperationRuleError, ValueError) as error:
            self.show_operation_error("进路建立失败", error)
            return
        self.recalculate_route_dependent_state()
        self.refresh_route_controls()
        self.refresh_view()

    def cancel_selected_route(self):
        if not self.require_communication("进路取消失败"):
            return
        route_id = self.active_route_combo.currentData()
        if route_id is None:
            return
        try:
            self.route_service.cancel_route(route_id)
        except ValueError as error:
            self.show_operation_error("进路取消失败", error)
            return
        self.recalculate_route_dependent_state()
        self.refresh_route_controls()
        self.refresh_view()

    def recalculate_route_dependent_state(self):
        for simulation in (self.simulation_a, self.simulation_b):
            simulation.update_all_track_codes()

    def refresh_route_controls(self):
        current_route_id = self.active_route_combo.currentData()
        self.active_route_combo.blockSignals(True)
        self.active_route_combo.clear()

        routes = self.route_service.active_routes()
        if routes:
            for route in routes:
                state_text = (
                    "已锁闭"
                    if route.state == RouteState.LOCKED
                    else "已建立"
                )
                self.active_route_combo.addItem(
                    f"{route.station}站｜{route.display_name}｜"
                    f"{route.track}｜{state_text}",
                    route.route_id,
                )

        if current_route_id is not None:
            index = self.active_route_combo.findData(current_route_id)
            if index >= 0:
                self.active_route_combo.setCurrentIndex(index)

        self.active_route_combo.blockSignals(False)
        self._sync_route_cancel_button()

    def _sync_route_cancel_button(self):
        route_id = self.active_route_combo.currentData()
        route = next(
            (
                item
                for item in self.route_service.active_routes()
                if item.route_id == route_id
            ),
            None,
        )
        self.route_cancel_button.setEnabled(
            self.communication_ready()
            and route is not None
            and route.state == RouteState.ESTABLISHED
        )
        self.active_route_combo.setToolTip(
            self.active_route_combo.currentText()
            if route is not None
            else "选择需要取消的已建立进路"
        )

    def clear_all_trains(self):
        if not self.require_communication("一键清车失败"):
            return
        self.engine.pause()
        self.train_service.clear_all_trains()
        self._train_control_drafts.clear()
        # 列车全部移除后，保留既有进路，但解除列车造成的锁闭，
        # 避免进路继续引用已经不存在的列车。
        self.route_service.reset_locks()
        for simulation in (self.simulation_a, self.simulation_b):
            simulation.train_position = None
            for track in simulation.track_circuits.values():
                track.release()
            simulation.close_signal()
            simulation.update_all_track_codes()
        self.refresh_route_controls()
        self.refresh_view()

    def get_balise_information(self, balise_id):
        if not self.is_connected():
            packets = ["ETCS-254"]
        else:
            station = None
            if balise_id.startswith("A站"):
                station = "A"
            elif balise_id.startswith("B站"):
                station = "B"

            routes = self.route_service.active_routes(station) if station else []
            route = routes[0] if routes else None
            if route is None:
                packets = ["ETCS-5", "ETCS-132", "ETCS-137"]
            elif route.route_type == RouteType.MAIN_RECEIVE:
                packets = ["ETCS-5"]
            elif route.route_type == RouteType.SIDE_RECEIVE:
                packets = [
                    "ETCS-5",
                    "ETCS-27",
                    "ETCS-68",
                    "ETCS-44(CTCS-1)",
                ]
            elif route.route_type == RouteType.SIDE_DEPART:
                packets = ["ETCS-5", "ETCS-27", "ETCS-68", "CTCS-1"]
            else:
                packets = ["ETCS-5", "ETCS-27"]
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

        if not self.require_communication("仿真复位失败"):
            return

        dispatched = [
            train
            for train in self.train_service.trains.values()
            if train.status in ("RUNNING", "STOPPED", "ARRIVED")
        ]
        if not dispatched:
            self.show_operation_error(
                "仿真复位失败",
                OperationRuleError(
                    "当前没有已经发车的列车",
                    "运行、暂停和已到达列车数量均为 0。",
                    "请先发出列车后再执行全局复位。",
                ),
            )
            self.refresh_control_states()
            return

        self.engine.pause()
        self.train_service.reset_dispatched_trains()
        for track_code, track in self.simulation_b.track_circuits.items():
            source_track = self.simulation_a.track_circuits[track_code]
            if source_track.occupied:
                track.occupy()
            else:
                track.release()
        self.simulation_b.update_all_track_codes()

        self.engine.reset_time()

        self.refresh_route_controls()
        self.refresh_view()

    # ==============================
    # 刷新
    # ==============================

    def refresh_view(self):

        self.refresh_route_controls()

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
            routes=[
                route.to_dict()
                for route in self.route_service.active_routes()
            ],
            station_codes={
                "A": self.simulation_a.get_station_track_codes(),
                "B": self.simulation_b.get_station_track_codes(),
            },
        )

        self.update_train_selector(
            trains
        )

        self.refresh_train_info(
            trains
        )
        self.sync_selected_train_controls()

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

        self.refresh_control_states()

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

    def sync_selected_train_controls(self, _train_id=None):
        train_id = self.train_selector.currentText()
        train = self.train_service.trains.get(train_id)
        combos = (
            self.departure_mode_combo,
            self.arrival_mode_combo,
            self.max_speed_combo,
        )
        for combo in combos:
            combo.blockSignals(True)

        try:
            if train is None:
                self.departure_mode_combo.setCurrentText("正线发车")
                self.arrival_mode_combo.setCurrentText("正线接车")
                self.max_speed_combo.setCurrentText("120 km/h")
                for combo in combos:
                    combo.setEnabled(False)
                return

            draft = self._train_control_drafts.get(train_id)
            if draft is None:
                draft = {
                    "departure": (
                        "侧线发车"
                        if train.departure_mode == "SIDE"
                        else "正线发车"
                    ),
                    "arrival": (
                        "侧线接车"
                        if train.arrival_mode == "SIDE"
                        else "正线接车"
                    ),
                    "max_speed": f"{int(train.max_speed)} km/h",
                }
                self._train_control_drafts[train_id] = draft

            self.departure_mode_combo.setCurrentText(draft["departure"])
            self.arrival_mode_combo.setCurrentText(draft["arrival"])
            self.max_speed_combo.setCurrentText(
                f"{int(train.max_speed)} km/h"
            )

            modes_editable = train.status == "WAITING"
            self.departure_mode_combo.setEnabled(modes_editable)
            self.arrival_mode_combo.setEnabled(modes_editable)
            self.max_speed_combo.setEnabled(
                train.status in ("WAITING", "RUNNING", "STOPPED")
            )
        finally:
            for combo in combos:
                combo.blockSignals(False)

    def on_selected_train_changed(self, _train_id=None):
        self.sync_selected_train_controls()
        self.refresh_train_info(self.train_service.get_all_train_status())
        self.refresh_control_states()

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

        A、B面板完全对等，启动顺序决定内部通信角色。

        两侧各有独立的TCC与改方管理器，
        因此两站的改方按钮都可以使用。
        """

        # --------------------------
        # A站：动态角色
        # --------------------------

        self.panel_a.network_button.setEnabled(
            True
        )

        self.panel_a.network_button.setToolTip(
            "启动A站通信；若先启动则等待对端，后启动则自动建立连接"
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
        # B站：动态角色
        # --------------------------

        self.panel_b.network_button.setEnabled(
            True
        )

        self.panel_b.network_button.setToolTip(
            "启动B站通信；若先启动则等待对端，后启动则自动建立连接"
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
        站间通信是否已经建立。
        """

        return self.communication_ready()

    def communication_ready(self):
        return self.connected_stations == {"A", "B"}

    def require_communication(self, title):
        if self.communication_ready():
            return True

        missing = [
            f"{station}站"
            for station in ("A", "B")
            if station not in self.connected_stations
        ]
        error = OperationRuleError(
            "A站和B站尚未全部建立通信",
            f"未连通站点：{'、'.join(missing) or '未知'}。",
            "请依次点击A站和B站的“启动通信”，待两站均显示“已连接”后重试。",
        )
        QMessageBox.warning(self, title, error.format_message())
        return False

    def show_operation_error(self, title, error):
        if isinstance(error, OperationRuleError):
            message = error.format_message()
        else:
            message = OperationRuleError(
                "请求未能完成",
                str(error),
                "请根据当前状态调整操作条件后重试。",
            ).format_message()
        QMessageBox.warning(self, title, message)

    def refresh_control_states(self):
        ready = self.communication_ready()
        has_trains = bool(self.train_service.trains)
        selected_train = self.train_service.trains.get(
            self.train_selector.currentText()
        )
        active_trains = [
            train
            for train in self.train_service.trains.values()
            if train.status in ("RUNNING", "STOPPED")
        ]
        dispatched_trains = [
            train
            for train in self.train_service.trains.values()
            if train.status in ("RUNNING", "STOPPED", "ARRIVED")
        ]
        self.operation_area.setEnabled(ready)
        self.panel_a.direction_button.setEnabled(ready)
        self.panel_b.direction_button.setEnabled(ready)

        self.start_button.setEnabled(
            ready
            and selected_train is not None
            and selected_train.status == "WAITING"
        )
        self.pause_button.setEnabled(ready and bool(active_trains))
        self.pause_button.setText(
            "Ⅱ 暂停"
            if self.engine.timer.isActive()
            else "▶ 继续"
            if self.train_service.globally_paused
            and any(train.status == "STOPPED" for train in active_trains)
            else "Ⅱ 暂停"
        )
        self.reset_button.setEnabled(ready and bool(dispatched_trains))
        self.clear_trains_button.setEnabled(
            ready and has_trains
        )
        self.tsr_cancel_button.setEnabled(
            ready and self.active_tsr_combo.currentData() is not None
        )
        self._sync_route_cancel_button()
        self.sync_selected_train_controls()

        for station in ("A", "B"):
            panel = self.get_panel_by_role(station)
            started = station in self.network_workers
            panel.network_button.setEnabled(not started)
            panel.disconnect_button.setEnabled(started)

    # ==========================================
    # 站间通信
    # ==========================================

    def start_network(self, role=None):
        """
        开启站间通信。

        首个启动的站建立监听，后启动的站自动连接先启动站。
        角色只用于内部通信，不显示在界面中。
        """

        if role is None:
            return

        # 该站别已经启动过
        if role in self.network_workers:
            return

        panel = self.get_panel_by_role(role)

        if self.network_server_station is None:
            self.network_server_station = role
            mode = "SERVER"
            panel.set_network_status("通信状态：等待对端启动")
        else:
            mode = "CLIENT"
            panel.set_network_status("通信状态：正在建立连接")

        self.network_modes[role] = mode
        host, port = self.network_endpoint()

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
        self.refresh_control_states()

    def network_worker_class(self, role):
        if role == self.network_server_station:
            return ServerNetworkWorker
        return ClientNetworkWorker

    @staticmethod
    def network_endpoint():
        return ("127.0.0.1", 9000)

    def disconnect_network(self, role):
        if self._network_resetting:
            return

        self._network_resetting = True
        self.train_service.pause_all()
        self.engine.pause()
        self.connected_stations.clear()
        workers = list(self.network_workers.values())
        self.network_workers.clear()
        self.network_modes.clear()
        self.network_server_station = None

        try:
            for worker in workers:
                worker.stop()
            for worker in workers:
                worker.wait(1000)
            for panel in (self.panel_a, self.panel_b):
                panel.network_button.setEnabled(True)
                panel.disconnect_button.setEnabled(False)
                panel.set_network_status("通信状态：未启动")
        finally:
            self._network_resetting = False
            self.refresh_control_states()

    def on_connected(self, role):

        if role not in self.network_workers:
            return

        self.connected_stations.add(role)

        self.get_panel_by_role(role).set_network_status(
            "通信状态：已连接"
        )
        self.get_panel_by_role(role).disconnect_button.setEnabled(True)

        # 连上以后立即同步一次
        self.send_track_status()
        self.send_signal_status(role)
        self.refresh_control_states()

    def on_disconnected(self, role):
        self.disconnect_network(role)

    def on_network_error(self, role, error_message):

        # 主动断开时端点已从活动表移除，随后到达的socket关闭错误
        # 属于预期线程收尾，不应覆盖已经复位的界面状态。
        if role not in self.network_workers:
            return

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

        if not self.require_communication("无法申请改方"):
            return

        worker = self.network_workers.get(role)

        if worker is None or not worker.running:
            self.show_operation_error(
                "无法申请改方",
                OperationRuleError(
                    f"{role}站无法发送区间改方申请",
                    "该站通信端点未运行。",
                    "请断开两站通信并重新启动，待两站均显示“已连接”后重试。",
                ),
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

                self.show_operation_error(
                    "无法改方",
                    OperationRuleError(
                        f"{role}站区间改方申请被拒绝",
                        reason,
                        "请确认区间空闲、信号关闭，且申请站已建立发车进路。",
                    ),
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
