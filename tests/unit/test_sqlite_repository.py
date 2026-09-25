"""SQLite 历史仓库的迁移、隔离与参数化测试。"""

from pathlib import Path

import pytest

from app.infrastructure.sqlite_repository import (
    DirectionAuthorityEntry,
    OperationLogEntry,
    SQLiteRepository,
    TelegramHistoryEntry,
)
from app.core.enums import RunningDirection


def test_schema_is_idempotent_and_station_queries_are_isolated(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    first = SQLiteRepository(path)
    first.append_operation(OperationLogEntry("A", 1000, "占用 Q1", True, "成功", 1, {"id": "Q1"}))
    first.append_operation(OperationLogEntry("B", 1001, "占用 Q2", True, "成功", 2, {"id": "Q2"}))
    first.close()

    reopened = SQLiteRepository(path)

    assert [item.station_id for item in reopened.list_operations("A")] == ["A"]
    assert [item.station_id for item in reopened.list_operations("B")] == ["B"]
    assert reopened.schema_version == 2


def test_authoritative_direction_and_recovery_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    repository = SQLiteRepository(path)
    repository.save_direction_authority(
        DirectionAuthorityEntry(
            "A",
            RunningDirection.B_TO_A,
            2000,
            7,
            {"transaction_id": "tx-1", "requester_applied": True},
        )
    )
    repository.close()

    restored = SQLiteRepository(path).load_direction_authority("A")

    assert restored is not None
    assert restored.direction is RunningDirection.B_TO_A
    assert restored.state_version == 7
    assert restored.recovery == {
        "transaction_id": "tx-1",
        "requester_applied": True,
    }


def test_values_are_parameterized_and_telegram_roundtrips(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "history.db")
    hostile = "Q1'); DROP TABLE operation_logs; --"
    repository.append_operation(
        OperationLogEntry("A", 1000, hostile, False, "非法输入", 0, {"raw": hostile})
    )
    repository.append_telegram(
        TelegramHistoryEntry(
            station_id="A",
            event_time_ms=1100,
            balise_id="B_A_CTL",
            template_id="TG_A_DEFAULT",
            mode="DEFAULT",
            logical_payload={"packets": []},
            simulation_hex="7B7D",
            crc32="AABBCCDD",
        )
    )

    assert repository.list_operations("A")[0].operation == hostile
    telegram = repository.list_telegrams("A")[0]
    assert telegram.logical_payload == {"packets": []}
    assert telegram.crc32 == "AABBCCDD"


def test_closed_repository_rejects_new_work(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "history.db")
    repository.close()

    with pytest.raises(RuntimeError, match="已关闭"):
        repository.list_operations("A")
