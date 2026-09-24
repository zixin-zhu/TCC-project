"""CTCS-2 教学应答器组配置约束测试。"""

import json
from pathlib import Path

import pytest

from app.core.exceptions import ConfigError
from app.infrastructure.config_loader import load_project_config
from tests.unit.test_config_loader import _valid_project, _write_json


def _mutate_balises(tmp_path: Path, mutate) -> Path:
    root = _valid_project(tmp_path)
    path = root / "balise_groups.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload["groups"][0]["balises"])
    _write_json(path, payload)
    return root


def test_group_rejects_duplicate_order(tmp_path: Path) -> None:
    """防止组内通过顺序不唯一。"""
    root = _mutate_balises(tmp_path, lambda items: items[1].update(order=1))

    with pytest.raises(ConfigError, match=r"groups\[0\]\.balises\[1\]\.order"):
        load_project_config(root, "A")


@pytest.mark.parametrize("missing_field", ["leu_port_id", "default_telegram_id"])
def test_controlled_balise_requires_leu_and_default_telegram(
    tmp_path: Path, missing_field: str
) -> None:
    """防止可控应答器在输入异常时没有确定的默认路径。"""
    root = _mutate_balises(tmp_path, lambda items: items[1].pop(missing_field))

    with pytest.raises(ConfigError, match=rf"balises\[1\]\.{missing_field}"):
        load_project_config(root, "A")


def test_fixed_balise_cannot_bind_leu_port(tmp_path: Path) -> None:
    """防止固定应答器错误进入动态 LEU 选择链路。"""
    root = _mutate_balises(
        tmp_path, lambda items: items[0].update(leu_port_id="LEU_A_1")
    )

    with pytest.raises(ConfigError, match=r"balises\[0\]\.leu_port_id"):
        load_project_config(root, "A")
