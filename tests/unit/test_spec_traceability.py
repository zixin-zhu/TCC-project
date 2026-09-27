"""CTCS-2 规范追踪文档的完整性测试。

该测试不判断规范内容的技术正确性，只保证每个追踪 ID 都有记录，避免
后续阶段实现了代码却忘记把验收证据写进交接文档。
"""

from __future__ import annotations

import re
from pathlib import Path


PLAN_ROOT = Path(__file__).resolve().parents[2]
TRACEABILITY_PATH = PLAN_ROOT / "docs" / "ctcs2-spec-traceability.md"
EXPECTED_IDS = {f"SPEC-{index:02d}" for index in range(1, 17)}


def test_ctcs2_traceability_contains_all_requirement_ids() -> None:
    """规范追踪表必须覆盖方案中定义的 SPEC-01 至 SPEC-16。"""
    text = TRACEABILITY_PATH.read_text(encoding="utf-8")
    actual_ids = set(re.findall(r"\bSPEC-\d{2}\b", text))
    assert actual_ids == EXPECTED_IDS


def test_ctcs2_traceability_names_code_and_evidence_columns() -> None:
    """追踪表必须同时说明代码落点和验收证据，不能只有需求摘要。"""
    text = TRACEABILITY_PATH.read_text(encoding="utf-8")
    assert "软件落地点" in text
    assert "验收证据" in text
