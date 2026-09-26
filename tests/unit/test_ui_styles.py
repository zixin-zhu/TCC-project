"""经典浅色控制台主题与语义状态属性测试。"""

from PyQt5.QtWidgets import QLabel

from app.ui.styles import CLASSIC_CONSOLE_QSS, relay_text, set_semantic_state


def test_classic_console_theme_contains_required_palette_and_state_selectors() -> None:
    """主题必须落实设计基线，而不是在各窗口散落近似颜色。"""
    assert "#eef2f5" in CLASSIC_CONSOLE_QSS
    assert "#ffffff" in CLASSIC_CONSOLE_QSS
    assert "#07558f" in CLASSIC_CONSOLE_QSS
    assert "#b8c7d3" in CLASSIC_CONSOLE_QSS
    assert "#1f2d38" in CLASSIC_CONSOLE_QSS
    assert "#1976d2" in CLASSIC_CONSOLE_QSS
    assert '[severity="critical"]' in CLASSIC_CONSOLE_QSS
    assert '[connectionState="HEALTHY"]' in CLASSIC_CONSOLE_QSS
    assert '[trackState="OCCUPIED"]' in CLASSIC_CONSOLE_QSS
    assert "Microsoft YaHei" not in CLASSIC_CONSOLE_QSS
    assert "微软雅黑" not in CLASSIC_CONSOLE_QSS


def test_set_semantic_state_updates_dynamic_property(qtbot) -> None:  # type: ignore[no-untyped-def]
    label = QLabel()
    qtbot.addWidget(label)

    set_semantic_state(label, "connectionState", "HEALTHY")

    assert label.property("connectionState") == "HEALTHY"


def test_relay_text_uniformly_renders_one_and_zero() -> None:
    """问题 4：继电器状态必须统一为 1/0，避免 True/False 混用。"""
    assert relay_text(True) == "1"
    assert relay_text(False) == "0"
    # 确保不会意外输出 Python 布尔字面量
    assert relay_text(True) not in ("True", "true")
    assert relay_text(False) not in ("False", "false")
