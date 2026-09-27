# SDD ledger — plan: docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md

## 预检

- 当前分支：`codex/dual-station-dashboard`
- 计划工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 说明：官方 SDD workspace 脚本因沙箱无法写入 `.superpowers` 目录，本账本改放到 `docs/sdd-ledger/`，内容与原格式等价。
- 已有共享接口：阶段 1 输出本地权威状态和站间事务，阶段 2 消费轨道/方向状态，阶段 3 消费状态与 LEU/限速接口，阶段 5 消费协调器快照，阶段 6 消费日志与告警历史；实现必须保持这些接口方向，不让 UI 反写领域状态。

## 阶段状态

- 阶段 0：已完成（追踪表测试 2 passed；全量基线 287 passed）
- 阶段 1：未开始
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
