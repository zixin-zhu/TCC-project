# SDD ledger — plan: docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md

## 预检

- 当前分支：`codex/dual-station-dashboard`
- 计划工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 说明：官方 SDD workspace 脚本因沙箱无法写入 `.superpowers` 目录，本账本改放到 `docs/sdd-ledger/`，内容与原格式等价。
- 已有共享接口：阶段 1 输出本地权威状态和站间事务，阶段 2 消费轨道/方向状态，阶段 3 消费状态与 LEU/限速接口，阶段 5 消费协调器快照，阶段 6 消费日志与告警历史；实现必须保持这些接口方向，不让 UI 反写领域状态。

## 阶段状态

- 阶段 0：已完成（追踪表测试 2 passed；全量基线 287 passed）
- 阶段 1：已完成，待提交并推送
- 阶段 2：未开始
- 阶段 3：未开始
- 阶段 4：未开始
- 阶段 5：未开始
- 阶段 6：未开始
- 阶段 7：未开始
- 阶段 8：未开始

## 阶段 0 完成记录

- 代码提交：待提交
- 定向测试：`tests/unit/test_spec_traceability.py` → 2 passed
- 全量测试：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --basetemp=/tmp/tcc-pytest-bt` → 287 passed
- 环境说明：普通沙箱禁止 localhost 临时端口，网络测试必须在允许本地回环端口的权限下运行；授权运行后全量通过。
- 产物：`docs/ctcs2-spec-traceability.md`、`tests/unit/test_spec_traceability.py`
- 下一步：阶段 1，建立双站本地权威状态和站间安全事务。

## 阶段 1 完成记录

- 新增 `LocalAuthorityState` 不可变本站权威快照；`StationRuntimeState.from_runtime`
  复制本站轨道、信号、活动进路、报文版本和状态版本，远端状态仍只能进入
  `PeerSnapshot`。
- `TrackInputSource` 增加 `SHUNT`，保持列车、人工、故障、分路不良来源独立。
- 新增 `InterstationAgreement` 和 `can_change_direction()`：按双方轨道清空、
  活动进路、状态版本、快照新鲜度、事务阶段和锁闭状态对 A→B/B→A 对称检查。
- `PeerSnapshot` 与全量同步增加活动进路、方向安全锁闭元数据；增量边界更新保留
  元数据，非法类型会被协议层拒绝。
- `DirectionChangeMachine` 增加 `authority_station_id=None` 对称模式；生产
  `TccController` 使用该模式，A/B 均可按本次事务角色发起改方。旧默认构造保留
  A 权威兼容行为，避免历史测试和旧数据迁移立即失效。
- 新增 `reconcile_peer_direction()`：重连全量同步只做方向复核；双方方向不同
  时保持各自方向并进入 `FAULT_LOCKED`，不把 B 或 A 的投影快照直接覆盖本站。
- 方向持久化从仅 A 改为每个站保存本站方向和恢复证据；恢复证据只由事务请求方
  重发，避免把通信角色误当作业务权威。
- 阶段定向测试：本地权威/一致性/方向/同步/运行时 `52 passed`；控制器、方向
  服务和双站非 TCP 回归 `34 passed`。普通沙箱下 4 项真实 TCP 测试因禁止回环
  临时端口绑定未执行到业务断言，需在允许回环端口环境重跑。
- 交接下一步：允许回环端口后运行阶段 1 全量 pytest，记录真实结果，提交并推送；
  然后开始阶段 2 轨道状态、编码、信号和附录 1 防护逻辑。
