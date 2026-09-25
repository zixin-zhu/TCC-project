class Signal:
    """
    信号机模型

    用于描述信号机的编号、位置和当前灯色。
    """

    # 允许出现的信号灯状态
    RED = "红灯"
    YELLOW = "黄灯"
    YELLOW_GREEN = "黄绿灯"
    GREEN = "绿灯"

    def __init__(self, code, location):
        # 信号机编号，例如 S01
        self.code = code

        # 信号机所在位置
        self.location = location

        # 默认显示红灯
        self.aspect = self.RED

    def set_red(self):
        """设置红灯"""
        self.aspect = self.RED

    def set_yellow(self):
        """设置黄灯"""
        self.aspect = self.YELLOW

    def set_yellow_green(self):
        """设置黄绿灯"""
        self.aspect = self.YELLOW_GREEN

    def set_green(self):
        """设置绿灯"""
        self.aspect = self.GREEN

    def get_aspect(self):
        """获取当前信号显示"""
        return self.aspect