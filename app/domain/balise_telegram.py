"""CTCS-2 教学逻辑报文与仿真封装。

本模块不生成现场可用的 1023 位报文，不实现 BCH、扰码或射频调制。
"""

import json
import zlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from app.core.enums import BaliseKind
from app.core.models import ProjectConfig


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class TelegramPacket:
    packet_id: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class LogicalTelegram:
    template_id: str
    group_id: str
    balise_id: str
    direction: str
    state_version: int
    packets: Tuple[TelegramPacket, ...]


@dataclass(frozen=True)
class SimulationEnvelope:
    format: str
    canonical_json: str
    hex_payload: str
    crc32: str


class BaliseGroupValidator:
    """校验应答器组与所属线路区段的领域关系。"""

    @staticmethod
    def validate_all(project: ProjectConfig) -> Tuple[ValidationIssue, ...]:
        issues = []
        section_lengths = {
            section.id: section.length_m for section in project.topology.sections
        }
        for group in project.balise_groups.groups:
            section_length = section_lengths.get(group.section_id)
            if section_length is None:
                issues.append(ValidationIssue(f"groups.{group.id}.section_id", "未知区段"))
                continue
            seen_orders = set()
            for balise in group.balises:
                path = f"groups.{group.id}.{balise.id}"
                if balise.order in seen_orders:
                    issues.append(ValidationIssue(f"{path}.order", "组内顺序重复"))
                seen_orders.add(balise.order)
                if not 0 <= balise.position_m <= section_length:
                    issues.append(
                        ValidationIssue(f"{path}.position_m", "位置超出所属区段")
                    )
                if balise.kind is BaliseKind.CONTROLLED and (
                    not balise.leu_port_id or not balise.default_telegram_id
                ):
                    issues.append(
                        ValidationIssue(path, "可控应答器缺少 LEU 或默认报文")
                    )
        return tuple(issues)


class LogicalTelegramService:
    """按受控模板创建逻辑报文并进行字段级校验。"""

    def __init__(self, catalog: Mapping[str, Any]):
        self._definitions = catalog["packet_definitions"]
        self._templates = catalog["templates"]

    def build(
        self,
        template_id: str,
        group_id: str,
        balise_id: str,
        direction: str,
        state_version: int,
        overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> LogicalTelegram:
        if template_id not in self._templates:
            raise ValueError(f"未知逻辑报文模板：{template_id}")
        overrides = overrides or {}
        packets = []
        for item in self._templates[template_id]["packets"]:
            packet_id = item["packet_id"]
            fields: Dict[str, Any] = dict(item["fields"])
            fields.update(overrides.get(packet_id, {}))
            packets.append(TelegramPacket(packet_id, fields))
        return LogicalTelegram(
            template_id, group_id, balise_id, direction, state_version, tuple(packets)
        )

    def validate(self, telegram: LogicalTelegram) -> Tuple[ValidationIssue, ...]:
        issues = []
        if telegram.direction not in {"A_TO_B", "B_TO_A", "BOTH"}:
            issues.append(ValidationIssue("direction", "未知应答器报文方向"))
        template = self._templates.get(telegram.template_id)
        if template is None:
            issues.append(ValidationIssue("template_id", "未知逻辑报文模板"))
        else:
            expected_order = [item["packet_id"] for item in template["packets"]]
            actual_order = [packet.packet_id for packet in telegram.packets]
            if actual_order != expected_order:
                issues.append(ValidationIssue("packets", "信息包顺序与模板不一致"))
        for packet in telegram.packets:
            path = f"packets.{packet.packet_id}"
            definition = self._definitions.get(packet.packet_id)
            if definition is None:
                issues.append(ValidationIssue(path, "未知信息包"))
                continue
            required = definition["required"]
            for field_name, rule in required.items():
                field_path = f"{path}.{field_name}"
                if field_name not in packet.fields:
                    issues.append(ValidationIssue(field_path, "缺少必填字段"))
                    continue
                value = packet.fields[field_name]
                if rule["type"] == "string" and (not isinstance(value, str) or not value):
                    issues.append(ValidationIssue(field_path, "必须是非空字符串"))
                if rule["type"] == "number":
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        issues.append(ValidationIssue(field_path, "必须是数值"))
                        continue
                    if "min" in rule and value < rule["min"]:
                        issues.append(ValidationIssue(field_path, "小于允许下限"))
                    if "min_exclusive" in rule and value <= rule["min_exclusive"]:
                        issues.append(ValidationIssue(field_path, "必须大于允许下限"))
                    if "max" in rule and value > rule["max"]:
                        issues.append(ValidationIssue(field_path, "超过允许上限"))
            unknown = set(packet.fields).difference(required)
            for field_name in sorted(unknown):
                issues.append(ValidationIssue(f"{path}.{field_name}", "未知字段"))
            if packet.packet_id == "CTCS-2":
                start = packet.fields.get("start_m")
                end = packet.fields.get("end_m")
                if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start >= end:
                    issues.append(ValidationIssue(f"{path}.start_m", "起点必须小于终点"))
        return tuple(issues)


class SimulationEnvelopeCodec:
    """生成仅供本软件保存/展示的规范 JSON、HEX 和 CRC32。"""

    @staticmethod
    def encode(telegram: LogicalTelegram) -> SimulationEnvelope:
        payload = {
            "balise_id": telegram.balise_id,
            "direction": telegram.direction,
            "group_id": telegram.group_id,
            "packets": [
                {"fields": dict(packet.fields), "packet_id": packet.packet_id}
                for packet in telegram.packets
            ],
            "state_version": telegram.state_version,
            "template_id": telegram.template_id,
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        raw = canonical.encode("utf-8")
        return SimulationEnvelope(
            format="simulation_envelope",
            canonical_json=canonical,
            hex_payload=raw.hex().upper(),
            crc32=f"{zlib.crc32(raw) & 0xFFFFFFFF:08X}",
        )
