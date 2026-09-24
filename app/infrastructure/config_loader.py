"""JSON 配置加载与跨文件引用校验。"""

import json
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence, Type, TypeVar

from app.core.enums import (
    BaliseDirection,
    BaliseKind,
    NetworkRole,
    RouteType,
    RunningDirection,
    SectionKind,
)
from app.core.exceptions import ConfigError
from app.core.models import (
    BaliseConfig,
    BaliseGroupConfig,
    BaliseGroupsConfig,
    BoundaryConfig,
    LeuPortConfig,
    NetworkConfig,
    ProjectConfig,
    RouteConfig,
    SignalConfig,
    StationConfig,
    TopologyConfig,
    TrackSectionConfig,
)

EnumT = TypeVar("EnumT")


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{label}: 配置文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label}: JSON 格式错误：{exc.msg}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{label}: 顶层必须是对象")
    return value


def _required(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{path}.{key}: 缺少必填字段")
    return mapping[key]


def _enum(enum_type: Type[EnumT], value: Any, path: str) -> EnumT:
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)  # type: ignore[attr-defined]
        raise ConfigError(f"{path}: 未知值 {value!r}，允许值：{allowed}") from exc


def _object_list(value: Any, path: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError(f"{path}: 必须是数组")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"{path}[{index}]: 必须是对象")
    return value


def _unique(items: Iterable[Any], paths: Iterable[str]) -> None:
    seen = set()
    for item, path in zip(items, paths):
        if not isinstance(item, str) or not item:
            raise ConfigError(f"{path}: 必须是非空字符串")
        if item in seen:
            raise ConfigError(f"{path}: ID {item!r} 重复")
        seen.add(item)


def _load_station(root: Path, station_id: str) -> StationConfig:
    if station_id not in {"A", "B"}:
        raise ConfigError("station_id: 只能是 A 或 B")
    data = _read_json(root / f"station_{station_id.lower()}.json", "station")
    network = _required(data, "network", "station")
    if not isinstance(network, dict):
        raise ConfigError("station.network: 必须是对象")
    port = _required(network, "port", "station.network")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ConfigError("station.network.port: 必须是 1~65535 的整数")
    configured_station_id = str(_required(data, "station_id", "station"))
    if configured_station_id != station_id:
        raise ConfigError(
            "station.station_id: "
            f"配置值 {configured_station_id!r} 与请求站点 {station_id!r} 不一致"
        )
    return StationConfig(
        station_id=configured_station_id,
        station_name=str(_required(data, "station_name", "station")),
        network=NetworkConfig(
            role=_enum(
                NetworkRole,
                _required(network, "role", "station.network"),
                "station.network.role",
            ),
            host=str(_required(network, "host", "station.network")),
            port=port,
            peer_station_id=str(
                _required(network, "peer_station_id", "station.network")
            ),
        ),
    )


def _load_topology(root: Path) -> TopologyConfig:
    data = _read_json(root / "topology.json", "topology")
    raw_sections = _object_list(
        _required(data, "sections", "topology"), "topology.sections"
    )
    ids = [item.get("id") for item in raw_sections]
    _unique(ids, (f"topology.sections[{i}].id" for i in range(len(ids))))
    sections_list: List[TrackSectionConfig] = []
    for i, item in enumerate(raw_sections):
        path = f"topology.sections[{i}]"
        try:
            length_m = float(_required(item, "length_m", path))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{path}.length_m: 必须是正数") from exc
        if length_m <= 0:
            raise ConfigError(f"{path}.length_m: 必须大于 0")
        sections_list.append(
            TrackSectionConfig(
                id=str(item["id"]),
                name=str(_required(item, "name", path)),
                kind=_enum(
                    SectionKind,
                    _required(item, "kind", path),
                    f"{path}.kind",
                ),
                length_m=length_m,
            )
        )
    sections = tuple(sections_list)
    section_set = set(ids)

    raw_signals = _object_list(data.get("signals", []), "topology.signals")
    _unique(
        (item.get("id") for item in raw_signals),
        (f"topology.signals[{i}].id" for i in range(len(raw_signals))),
    )
    signals: List[SignalConfig] = []
    for i, item in enumerate(raw_signals):
        protected = _required(item, "protects_section", f"topology.signals[{i}]")
        if protected not in section_set:
            raise ConfigError(
                f"topology.signals[{i}].protects_section: 未知区段 {protected!r}"
            )
        signals.append(SignalConfig(str(item["id"]), str(protected)))

    raw_routes = _object_list(data.get("routes", []), "topology.routes")
    _unique(
        (item.get("id") for item in raw_routes),
        (f"topology.routes[{i}].id" for i in range(len(raw_routes))),
    )
    routes: List[RouteConfig] = []
    for i, item in enumerate(raw_routes):
        path = f"topology.routes[{i}]"
        route_sections = item.get("sections")
        if not isinstance(route_sections, list) or not route_sections:
            raise ConfigError(f"{path}.sections: 必须是非空数组")
        for j, section_id in enumerate(route_sections):
            if section_id not in section_set:
                raise ConfigError(f"{path}.sections[{j}]: 未知区段 {section_id!r}")
        routes.append(
            RouteConfig(
                id=str(item["id"]),
                type=_enum(RouteType, _required(item, "type", path), f"{path}.type"),
                direction=_enum(
                    RunningDirection,
                    _required(item, "direction", path),
                    f"{path}.direction",
                ),
                sections=tuple(str(value) for value in route_sections),
            )
        )

    raw_boundaries = _object_list(data.get("boundaries", []), "topology.boundaries")
    _unique(
        (item.get("id") for item in raw_boundaries),
        (f"topology.boundaries[{i}].id" for i in range(len(raw_boundaries))),
    )
    boundaries: List[BoundaryConfig] = []
    for i, item in enumerate(raw_boundaries):
        path = f"topology.boundaries[{i}]"
        local = _required(item, "local_section", path)
        if local not in section_set:
            raise ConfigError(f"{path}.local_section: 未知区段 {local!r}")
        boundaries.append(
            BoundaryConfig(
                id=str(_required(item, "id", path)),
                local_section=str(local),
                peer_section=str(_required(item, "peer_section", path)),
            )
        )
    return TopologyConfig(sections, tuple(signals), tuple(routes), tuple(boundaries))


def _load_balise_groups(root: Path, topology: TopologyConfig) -> BaliseGroupsConfig:
    data = _read_json(root / "balise_groups.json", "balise_groups")
    templates = data.get("telegram_templates", [])
    if not isinstance(templates, list):
        raise ConfigError("telegram_templates: 必须是数组")
    _unique(templates, (f"telegram_templates[{i}]" for i in range(len(templates))))
    template_set = set(templates)
    raw_ports = _object_list(data.get("leu_ports", []), "leu_ports")
    port_ids = [item.get("id") for item in raw_ports]
    _unique(port_ids, (f"leu_ports[{i}].id" for i in range(len(port_ids))))
    port_set = set(port_ids)
    raw_groups = _object_list(data.get("groups", []), "groups")
    if not raw_groups:
        raise ConfigError("groups: 至少需要一个应答器组")
    _unique(
        (item.get("id") for item in raw_groups),
        (f"groups[{i}].id" for i in range(len(raw_groups))),
    )
    section_set = {section.id for section in topology.sections}
    all_balise_ids = set()
    groups: List[BaliseGroupConfig] = []
    for group_index, raw_group in enumerate(raw_groups):
        group_path = f"groups[{group_index}]"
        section_id = _required(raw_group, "section_id", group_path)
        if section_id not in section_set:
            raise ConfigError(f"{group_path}.section_id: 未知区段 {section_id!r}")
        raw_balises = _object_list(
            _required(raw_group, "balises", group_path), f"{group_path}.balises"
        )
        if not raw_balises:
            raise ConfigError(f"{group_path}.balises: 应答器组不能为空")
        orders = set()
        balises: List[BaliseConfig] = []
        for balise_index, raw_balise in enumerate(raw_balises):
            path = f"{group_path}.balises[{balise_index}]"
            balise_id = _required(raw_balise, "id", path)
            if balise_id in all_balise_ids:
                raise ConfigError(f"{path}.id: 应答器 ID {balise_id!r} 重复")
            all_balise_ids.add(balise_id)
            order = _required(raw_balise, "order", path)
            if type(order) is not int or order < 1:
                raise ConfigError(f"{path}.order: 必须是正整数")
            if order in orders:
                raise ConfigError(f"{path}.order: 组内顺序 {order} 重复")
            orders.add(order)
            kind = _enum(BaliseKind, _required(raw_balise, "kind", path), f"{path}.kind")
            fixed_id = raw_balise.get("fixed_telegram_id")
            leu_id = raw_balise.get("leu_port_id")
            default_id = raw_balise.get("default_telegram_id")
            if kind is BaliseKind.FIXED:
                if leu_id is not None:
                    raise ConfigError(f"{path}.leu_port_id: 固定应答器不能绑定 LEU")
                if not fixed_id:
                    raise ConfigError(f"{path}.fixed_telegram_id: 缺少固定报文")
                if fixed_id not in template_set:
                    raise ConfigError(f"{path}.fixed_telegram_id: 未知报文 {fixed_id!r}")
            else:
                if not leu_id:
                    raise ConfigError(f"{path}.leu_port_id: 可控应答器必须绑定 LEU")
                if leu_id not in port_set:
                    raise ConfigError(f"{path}.leu_port_id: 未知 LEU 端口 {leu_id!r}")
                if not default_id:
                    raise ConfigError(f"{path}.default_telegram_id: 可控应答器必须配置默认报文")
                if default_id not in template_set:
                    raise ConfigError(f"{path}.default_telegram_id: 未知报文 {default_id!r}")
            balises.append(
                BaliseConfig(
                    id=str(balise_id),
                    kind=kind,
                    order=order,
                    position_m=float(_required(raw_balise, "position_m", path)),
                    fixed_telegram_id=fixed_id,
                    leu_port_id=leu_id,
                    default_telegram_id=default_id,
                )
            )
        groups.append(
            BaliseGroupConfig(
                id=str(raw_group["id"]),
                direction=_enum(
                    BaliseDirection,
                    _required(raw_group, "direction", group_path),
                    f"{group_path}.direction",
                ),
                section_id=str(section_id),
                balises=tuple(sorted(balises, key=lambda item: item.order)),
            )
        )
    return BaliseGroupsConfig(
        telegram_templates=tuple(str(item) for item in templates),
        leu_ports=tuple(LeuPortConfig(str(item["id"])) for item in raw_ports),
        groups=tuple(groups),
    )


def validate_configuration(config: ProjectConfig) -> None:
    """执行依赖站点身份的最终校验。"""
    if config.station.station_id == config.station.network.peer_station_id:
        raise ConfigError("station.network.peer_station_id: 不能与本站相同")
    expected = NetworkRole.SERVER if config.station.station_id == "A" else NetworkRole.CLIENT
    if config.station.network.role is not expected:
        raise ConfigError(
            f"station.network.role: {config.station.station_id} 站必须为 {expected.value}"
        )


def load_project_config(config_dir: Path, station_id: str) -> ProjectConfig:
    """加载站点、拓扑和应答器组配置并返回强类型结果。"""
    root = Path(config_dir)
    station = _load_station(root, station_id.upper())
    topology = _load_topology(root)
    balise_groups = _load_balise_groups(root, topology)
    config = ProjectConfig(station, topology, balise_groups)
    validate_configuration(config)
    return config
