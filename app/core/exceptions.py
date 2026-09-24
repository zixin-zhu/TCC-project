"""应用可识别的异常类型。"""


class ConfigError(ValueError):
    """配置内容或引用不合法。"""


class UnknownTrackSectionError(KeyError):
    """轨道区段编号不存在。"""


class FrameError(ValueError):
    """TCP 长度帧格式不合法。"""


class ProtocolError(ValueError):
    """站间仿真协议报文不合法或不适用于当前连接。"""


class ConnectionClosedError(ConnectionError):
    """对端正常关闭或连接已不可继续使用。"""
