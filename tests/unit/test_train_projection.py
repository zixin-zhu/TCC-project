"""列车 2D 线路投影的纯领域测试。"""

from app.core.enums import RunningDirection
from app.core.models import TrackSectionConfig, TopologyConfig
from app.services.dual_train_coordinator import DualTrainState, DualTrainStatus
from app.services.train_projection import TrainProjectionMapper


def _topology() -> TopologyConfig:
    return TopologyConfig(
        sections=(
            TrackSectionConfig("A_T1", "A股道", "STATION", 100),
            TrackSectionConfig("Q1", "第一闭塞分区", "BLOCK", 200),
            TrackSectionConfig("B_T1", "B股道", "STATION", 100),
        ),
        signals=(),
        routes=(),
        boundaries=(),
    )


def test_projection_uses_topology_lengths_and_reverse_direction() -> None:
    mapper = TrainProjectionMapper(_topology(), scene_width=800.0)
    assert [item.section_id for item in mapper.sections] == ["A_T1", "Q1", "B_T1"]
    assert mapper.sections[0].x_start == 0.0
    assert mapper.sections[-1].x_end == 800.0

    forward = DualTrainState(
        "T001", RunningDirection.A_TO_B, "Q1", position_m=50.0, status=DualTrainStatus.RUNNING
    )
    reverse = DualTrainState(
        "T002", RunningDirection.B_TO_A, "Q1", position_m=50.0, status=DualTrainStatus.RUNNING
    )
    forward_item = mapper.project(forward)
    reverse_item = mapper.project(reverse)

    assert forward_item.x_center < reverse_item.x_center
    assert forward_item.section_id == reverse_item.section_id == "Q1"


def test_projection_clamps_out_of_range_positions() -> None:
    mapper = TrainProjectionMapper(_topology(), scene_width=800.0)
    train = DualTrainState(
        "T001", RunningDirection.A_TO_B, "A_T1", position_m=999.0, status=DualTrainStatus.RUNNING
    )
    item = mapper.project(train)
    assert item.x_center == mapper.sections[0].x_end
