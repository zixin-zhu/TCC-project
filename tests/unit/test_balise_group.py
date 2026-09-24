"""应答器组领域级校验测试。"""

from dataclasses import replace
from pathlib import Path

from app.domain.balise_telegram import BaliseGroupValidator
from app.infrastructure.config_loader import load_project_config


ROOT = Path(__file__).resolve().parents[2]


def test_repository_balise_groups_are_valid() -> None:
    project = load_project_config(ROOT / "configs", "A")

    assert BaliseGroupValidator.validate_all(project) == ()


def test_balise_position_must_be_inside_its_section() -> None:
    project = load_project_config(ROOT / "configs", "A")
    group = project.balise_groups.groups[0]
    invalid_balise = replace(group.balises[0], position_m=9999)
    invalid_group = replace(group, balises=(invalid_balise,) + group.balises[1:])
    invalid_project = replace(
        project,
        balise_groups=replace(
            project.balise_groups,
            groups=(invalid_group,) + project.balise_groups.groups[1:],
        ),
    )

    issues = BaliseGroupValidator.validate_all(invalid_project)

    assert any(issue.path.endswith("B_A_FIX.position_m") for issue in issues)
