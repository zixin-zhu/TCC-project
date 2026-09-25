class TrackCircuit:
    """
    轨道电路模型

    用于描述一个轨道区段的基本状态。
    """

    def __init__(self, code, name, length=1000):
        # 轨道电路编码，例如 G01
        self.code = code

        # 轨道电路名称
        self.name = name

        # 是否被列车占用
        # False = 空闲
        # True = 占用
        self.occupied = False
        self.track_code = "L5"
        # 闭塞分区长度，单位：米
        self.length = length
        self.signal_code = "L5"

    def set_track_code(self, track_code):
        """
        设置轨道电路编码
        """

        self.track_code = track_code

        # 同步写入自动闭塞码序，
        # 保证GUI读取的signal_code始终是最新计算结果
        self.signal_code = track_code

    def get_track_code(self):
        """
        获取当前轨道电路编码
        """

        return self.track_code

    def occupy(self):
        """列车进入轨道区段"""
        self.occupied = True

    def release(self):
        """列车离开轨道区段"""
        self.occupied = False

    def get_status(self):
        """获取轨道区段当前状态"""
        if self.occupied:
            return "占用"
        else:
            return "空闲"