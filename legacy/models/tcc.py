class TCC:
    """
    车站列控中心 TCC 模型

    一个TCC负责管理本站相关的：
    1. 轨道电路
    2. 信号机
    3. 有源应答器
    4. 区间运行方向
    """

    def __init__(self, code, station_name):
        # TCC编号，例如 TCC_A
        self.code = code

        # 所属车站
        self.station_name = station_name

        # 管理的轨道电路
        self.track_circuits = {}

        # 管理的信号机
        self.signals = {}

        # 管理的应答器
        self.balises = {}

        # 当前区间运行方向
        self.direction = "A_TO_B"

    def add_track_circuit(self, track):
        """添加轨道电路"""
        self.track_circuits[track.code] = track

    def add_signal(self, signal):
        """添加信号机"""
        self.signals[signal.code] = signal

    def add_balise(self, balise):
        """添加应答器"""
        self.balises[balise.code] = balise

    def get_track(self, code):
        """根据编号获取轨道电路"""
        return self.track_circuits.get(code)

    def get_signal(self, code):
        """根据编号获取信号机"""
        return self.signals.get(code)

    def get_balise(self, code):
        """根据编号获取应答器"""
        return self.balises.get(code)

    def set_direction(self, direction):
        """设置区间运行方向"""
        self.direction = direction

    def get_direction(self):
        """获取当前运行方向"""
        return self.direction