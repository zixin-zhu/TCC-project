"""配置驱动联合线路图的布局、不一致显示与只读命中测试。"""

from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QPoint

from app.core.enums import SectionKind, SignalAspect, TrackState
from app.infrastructure.config_loader import load_project_config
from app.core.models import BaliseGroupsConfig, TopologyConfig, TrackSectionConfig
from app.ui.corridor_overview_widget import CorridorOverviewWidget
from app.ui.dual_snapshot import SectionConsistency
from tests.integration.test_dual_dashboard import _model


ROOT = Path(__file__).resolve().parents[2]


def _topology() -> TopologyConfig:
    return TopologyConfig(
        sections=(
            TrackSectionConfig("SHORT", "短区段", SectionKind.BLOCK, 500),
            TrackSectionConfig("LONG", "长区段", SectionKind.BLOCK, 1500),
            TrackSectionConfig("TAIL", "尾部区段", SectionKind.BLOCK, 1000),
        ),
        signals=(),
        routes=(),
        boundaries=(),
    )


def test_corridor_layout_order_and_width_come_from_configuration(qtbot) -> None:  # type: ignore[no-untyped-def]
    widget = CorridorOverviewWidget(
        _topology(), BaliseGroupsConfig((), (), ())
    )
    widget.resize(1000, 360)
    qtbot.addWidget(widget)
    widget.show()
    widget.repaint()
    qtbot.wait(10)

    assert widget.section_order == ("SHORT", "LONG", "TAIL")
    rects = widget.section_rects
    assert rects["LONG"].width() > rects["TAIL"].width() > rects["SHORT"].width()
    assert widget.section_at(rects["LONG"].center()) == "LONG"
    assert widget.section_at(QPoint(0, 0)) is None


def test_corridor_exposes_and_draws_shared_inconsistency_text(qtbot) -> None:  # type: ignore[no-untyped-def]
    base = _model()
    sections = (
        SectionConsistency(
            "SHORT",
            TrackState.CLEAR,
            TrackState.CLEAR,
            True,
            TrackState.CLEAR,
            "双站状态一致",
        ),
        SectionConsistency(
            "LONG",
            TrackState.CLEAR,
            TrackState.OCCUPIED,
            False,
            None,
            "双站不一致：A=CLEAR，B=OCCUPIED",
        ),
        SectionConsistency(
            "TAIL",
            TrackState.OCCUPIED,
            TrackState.OCCUPIED,
            True,
            TrackState.OCCUPIED,
            "双站状态一致",
        ),
    )
    model = replace(base, sections=sections, operation_locked=True)
    widget = CorridorOverviewWidget(
        _topology(), BaliseGroupsConfig((), (), ())
    )
    qtbot.addWidget(widget)

    widget.set_snapshot(model)

    assert widget.section_status_text("LONG") == "不一致"
    assert "LONG：不一致" in widget.accessibleDescription()
    assert "安全锁闭" in widget.accessibleDescription()


def test_corridor_never_silently_chooses_one_station_signal(qtbot) -> None:  # type: ignore[no-untyped-def]
    model = _model()
    signals_b = dict(model.station_b.signals)
    signals_b["SA"] = replace(signals_b["SA"], aspect=SignalAspect.RED)
    station_b = replace(model.station_b, signals=signals_b)
    divergent = replace(model, station_b=station_b, operation_locked=True)
    config = load_project_config(ROOT / "configs", "A")
    widget = CorridorOverviewWidget(config.topology, config.balise_groups)
    qtbot.addWidget(widget)

    widget.set_snapshot(divergent)

    assert "信号不一致" in widget.signal_status_text("SA")
    assert "SA：信号不一致" in widget.accessibleDescription()
