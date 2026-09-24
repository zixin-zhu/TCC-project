"""项目配置加载与交叉引用校验测试。"""

import json
from pathlib import Path

import pytest

from app.core.enums import NetworkRole
from app.core.exceptions import ConfigError
from app.infrastructure.config_loader import load_project_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _valid_project(tmp_path: Path) -> Path:
    _write_json(
        tmp_path / "station_a.json",
        {
            "station_id": "A",
            "station_name": "A站",
            "network": {
                "role": "SERVER",
                "host": "127.0.0.1",
                "port": 9500,
                "peer_station_id": "B",
            },
        },
    )
    _write_json(
        tmp_path / "topology.json",
        {
            "sections": [
                {"id": "A_T1", "name": "A站股道", "kind": "STATION", "length_m": 800},
                {"id": "Q1", "name": "第一闭塞分区", "kind": "BLOCK", "length_m": 1200},
            ],
            "signals": [{"id": "SA", "protects_section": "Q1"}],
            "routes": [
                {
                    "id": "A_DEPART",
                    "type": "DEPARTURE",
                    "direction": "A_TO_B",
                    "sections": ["A_T1", "Q1"],
                }
            ],
            "boundaries": [
                {"id": "AB", "local_section": "Q1", "peer_section": "Q4"}
            ],
        },
    )
    _write_json(
        tmp_path / "balise_groups.json",
        {
            "telegram_templates": ["TG_FIXED_A", "TG_DEFAULT_A"],
            "leu_ports": [{"id": "LEU_A_1"}],
            "groups": [
                {
                    "id": "BG_A_01",
                    "direction": "A_TO_B",
                    "section_id": "A_T1",
                    "balises": [
                        {
                            "id": "B_A_FIX",
                            "kind": "FIXED",
                            "order": 1,
                            "position_m": 100,
                            "fixed_telegram_id": "TG_FIXED_A",
                        },
                        {
                            "id": "B_A_CTL",
                            "kind": "CONTROLLED",
                            "order": 2,
                            "position_m": 105,
                            "leu_port_id": "LEU_A_1",
                            "default_telegram_id": "TG_DEFAULT_A",
                        },
                    ],
                }
            ],
        },
    )
    return tmp_path


def test_valid_configuration_loads_typed_objects(tmp_path: Path) -> None:
    """防止合法 JSON 只以不受约束的字典流入业务层。"""
    config = load_project_config(_valid_project(tmp_path), "A")

    assert config.station.station_id == "A"
    assert config.station.network.role is NetworkRole.SERVER
    assert [section.id for section in config.topology.sections] == ["A_T1", "Q1"]
    assert config.balise_groups.groups[0].balises[1].leu_port_id == "LEU_A_1"


@pytest.mark.parametrize("port", [0, 65536, "9500"])
def test_invalid_port_reports_exact_field_path(tmp_path: Path, port: object) -> None:
    """防止非法端口延迟到网络启动时才暴露。"""
    root = _valid_project(tmp_path)
    station_path = root / "station_a.json"
    station = json.loads(station_path.read_text(encoding="utf-8"))
    station["network"]["port"] = port
    _write_json(station_path, station)

    with pytest.raises(ConfigError, match=r"station\.network\.port"):
        load_project_config(root, "A")


def test_duplicate_section_id_is_rejected(tmp_path: Path) -> None:
    """防止重复区段使拓扑引用产生二义性。"""
    root = _valid_project(tmp_path)
    topology_path = root / "topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    topology["sections"].append(dict(topology["sections"][0]))
    _write_json(topology_path, topology)

    with pytest.raises(ConfigError, match=r"topology\.sections\[2\]\.id"):
        load_project_config(root, "A")


def test_dangling_signal_section_reference_is_rejected(tmp_path: Path) -> None:
    """防止信号机引用不存在的防护区段。"""
    root = _valid_project(tmp_path)
    topology_path = root / "topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    topology["signals"][0]["protects_section"] = "Q404"
    _write_json(topology_path, topology)

    with pytest.raises(
        ConfigError, match=r"topology\.signals\[0\]\.protects_section"
    ):
        load_project_config(root, "A")


def test_repository_configs_define_two_independent_station_roles() -> None:
    """防止正式配置退化为同进程双站或相同网络角色。"""
    config_dir = PROJECT_ROOT / "configs"

    station_a = load_project_config(config_dir, "A")
    station_b = load_project_config(config_dir, "B")

    assert station_a.station.network.role is NetworkRole.SERVER
    assert station_b.station.network.role is NetworkRole.CLIENT
    assert station_a.topology == station_b.topology
    assert {group.id for group in station_a.balise_groups.groups} == {
        "BG_A_01",
        "BG_B_01",
    }


def test_station_file_identity_must_match_requested_station(tmp_path: Path) -> None:
    """防止复制配置后忘记修改站点 ID，造成对站身份混乱。"""
    root = _valid_project(tmp_path)
    path = root / "station_a.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["station_id"] = "B"
    _write_json(path, payload)

    with pytest.raises(ConfigError, match=r"station\.station_id"):
        load_project_config(root, "A")


def test_duplicate_boundary_id_is_rejected(tmp_path: Path) -> None:
    """防止两个边界定义共享 ID，导致邻站快照更新错误对象。"""
    root = _valid_project(tmp_path)
    path = root / "topology.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["boundaries"].append(dict(payload["boundaries"][0]))
    _write_json(path, payload)

    with pytest.raises(ConfigError, match=r"topology\.boundaries\[1\]\.id"):
        load_project_config(root, "A")


def test_section_length_must_be_positive(tmp_path: Path) -> None:
    """防止非正长度进入列车位置和里程计算。"""
    root = _valid_project(tmp_path)
    path = root / "topology.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sections"][0]["length_m"] = 0
    _write_json(path, payload)

    with pytest.raises(ConfigError, match=r"topology\.sections\[0\]\.length_m"):
        load_project_config(root, "A")
