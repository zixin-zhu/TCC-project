# TCC CTCS-2 分阶段执行索引

> 规格入口：`/Users/zhu/Desktop/列控课设/TCC_Codex_Vibe_Coding_改造实施方案.md`。本文件用于任务恢复和版本切分；技术细节以对应阶段子方案为准。

## 全局执行约束

- 分支：`codex/ctcs2-rebuild`；每个 Task 独立提交并推送。
- 严格执行 RED—GREEN—REFACTOR；阶段结束运行本阶段和全部已有回归。
- 代码模块化、类型化；公共类、复杂业务规则、状态转换和安全降级必须有准确中文注释或 docstring，禁止逐行重复代码含义的无效注释。
- 如需 IDE，仅使用 PyCharm；UI 沿用旧版配色、布局密度和绘制风格。
- 每个 Task 完成时更新 `docs/IMPLEMENTATION_STATUS.md`。

## Task 1：工程骨架、配置与统一领域模型

读取：`/Users/zhu/Desktop/列控课设/docs/tcc-vibe-plans/01-foundation-domain.md`。

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
