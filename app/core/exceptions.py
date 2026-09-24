"""应用可识别的异常类型。"""


class ConfigError(ValueError):
    """配置内容或引用不合法。"""


class UnknownTrackSectionError(KeyError):
    """轨道区段编号不存在。"""
