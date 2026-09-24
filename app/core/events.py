"""不依赖 Qt 的领域事件定义。"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DomainEvent:
    """用于跨层传递、可序列化的领域事件。"""

    event_type: str
    state_version: int
    payload: Mapping[str, Any]
