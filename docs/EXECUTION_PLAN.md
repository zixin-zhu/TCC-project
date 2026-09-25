# TCC CTCS-2 分阶段执行索引

> 当前规格入口：`docs/dual-station-plans/00-dual-station-design-spec.md`；阶段入口：
> `docs/dual-station-plans/README.md`。原 CTCS-2 阶段 1～7 已完成，保留在本文后半部作为历史索引。

## 全局执行约束

- 当前分支：`codex/dual-station-dashboard`；已完成基线分支
  `codex/ctcs2-rebuild` 不再接收本轮实现提交。每个阶段独立提交并推送。
- 严格执行 RED—GREEN—REFACTOR；阶段结束运行本阶段和全部已有回归。
- 代码模块化、类型化；公共类、复杂业务规则、状态转换和安全降级必须有准确中文注释或 docstring，禁止逐行重复代码含义的无效注释。
- 如需 IDE，仅使用 PyCharm；UI 采用用户参考图方案一的浅色经典控制台风格。
- 每个 Task 完成时更新 `docs/IMPLEMENTATION_STATUS.md`。

## 当前执行顺序：双站同屏阶段 0～5

1. `docs/dual-station-plans/00-workspace-git-recovery.md`
2. `docs/dual-station-plans/01-dual-runtime-lifecycle.md`
3. `docs/dual-station-plans/02-station-ui-refactor.md`
4. `docs/dual-station-plans/03-dashboard-corridor.md`
5. `docs/dual-station-plans/04-dual-operations-train.md`
6. `docs/dual-station-plans/05-integration-delivery.md`

恢复时读取 `docs/IMPLEMENTATION_STATUS.md`，从双站同屏阶段表中首个“进行中”或
“未开始”阶段继续。阶段 N 未完成测试、复审、提交和推送前，禁止开始阶段 N+1。

## 历史索引：已完成 CTCS-2 阶段 1～7

## Task 1：工程骨架、配置与统一领域模型

读取：`/Users/zhu/Desktop/TCC-project/docs/tcc-vibe-plans/01-foundation-domain.md`。

产出：`app/core`、配置加载/校验、A/B 和拓扑/应答器组配置、`run.py --validate-only`、Qt 诊断、pytest 基线。

验证：`python -m pytest tests/unit/test_config_loader.py tests/unit/test_runtime_state.py tests/unit/test_balise_group_config.py -q`，再运行 `python -m pytest -q` 和两站 `--validate-only`。

## Task 2：CTCS-2 轨道编码、进路与信号点灯

读取：`02-ctcs2-track-signal.md`。产出进路、编码、信号控制服务及配置化规则。验证三个领域测试及全量回归。

## Task 3：CTCS-2 应答器组、LEU、逻辑报文与临时限速

读取：`03-ctcs2-balise-leu.md`。产出五类最小信息包、LEU 默认路径、限速生命周期和仿真封装。验证对应五组测试及全量回归。

## Task 4：双站协议、网络线程、心跳与同步

读取：`04-peer-network.md`。产出长度帧、协议、worker、握手、心跳、重连和同步。验证单元/集成/线程测试及全量回归。

## Task 5：区间改方事务与失败恢复

读取：`05-direction-change.md`。产出四阶段改方状态机。验证单元/双端集成测试及全量回归。

## Task 6：控制器、单站 UI、日志告警与持久化

读取：`06-ui-persistence.md`。产出统一控制器、SQLite/日志/告警和沿用原风格的单站 UI。验证单元、pytest-qt 与全量回归。

## Task 7：列车演示、场景、双站验收与交付

读取：`07-integration-delivery.md`。产出列车适配、七类场景、启动脚本、README 和交付证据。验证全套 pytest、双站人工验收与关闭清理。
