"""TCC 教学仿真的公共枚举。

枚举集中定义可避免旧代码中中文字符串、英文字符串和魔法值混用。
配置与协议使用英文值，界面层负责中文显示。
"""

from enum import Enum


class TrackInputSource(str, Enum):
    """轨道状态输入来源；各来源必须独立保存。"""

    TRAIN = "TRAIN"
    OPERATOR = "OPERATOR"
    FAULT = "FAULT"


class TrackState(str, Enum):
    CLEAR = "CLEAR"
    OCCUPIED = "OCCUPIED"
    FAULT_OCCUPIED = "FAULT_OCCUPIED"
    SHUNT_BAD = "SHUNT_BAD"


class RunningDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"


class TrackCode(str, Enum):
    NONE = "NONE"
    DETECT = "DETECT"
    HU = "HU"
    U = "U"
    LU = "LU"
    L = "L"
    L2 = "L2"
    L3 = "L3"
    L5 = "L5"


class SignalAspect(str, Enum):
    DARK = "DARK"
    RED = "RED"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE_YELLOW"
    GREEN = "GREEN"
    RED_LAMP_FAILURE = "RED_LAMP_FAILURE"


class BaliseKind(str, Enum):
    FIXED = "FIXED"
    CONTROLLED = "CONTROLLED"


class TelegramMode(str, Enum):
    FIXED = "FIXED"
    SELECTED = "SELECTED"
    DEFAULT = "DEFAULT"
    FAULT_DEFAULT = "FAULT_DEFAULT"


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    HANDSHAKING = "HANDSHAKING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


class DirectionPhase(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    WAIT_PEER = "WAIT_PEER"
    APPROVED = "APPROVED"
    COMMITTING = "COMMITTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAULT_LOCKED = "FAULT_LOCKED"


class NetworkRole(str, Enum):
    SERVER = "SERVER"
    CLIENT = "CLIENT"


class SectionKind(str, Enum):
    STATION = "STATION"
    BLOCK = "BLOCK"


class RouteType(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class BaliseDirection(str, Enum):
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"
    BOTH = "BOTH"
