# TCC 单界面双站改造阶段方案索引

本目录只提供设计基线和六份独立阶段方案，不提供可跳过阶段门禁的单体总方案。
执行时按下列顺序逐份读取；每一阶段必须完成测试、独立复审、提交和推送后，
才可进入下一阶段。

| 顺序 | 文档 | 交付结果 |
|---|---|---|
| 设计基线 | [00-dual-station-design-spec.md](00-dual-station-design-spec.md) | 单进程双站、经典控制台 UI、状态来源和安全边界 |
| 阶段 0 | [00-workspace-git-recovery.md](00-workspace-git-recovery.md) | 修复目录改名后的 linked worktree，建立开发分支 |
| 阶段 1 | [01-dual-runtime-lifecycle.md](01-dual-runtime-lifecycle.md) | A/B 双运行时顺序启动、真实 TCP 与可靠关闭 |
| 阶段 2 | [02-station-ui-refactor.md](02-station-ui-refactor.md) | 可嵌入单站组件与方案一经典控制台主题 |
| 阶段 3 | [03-dashboard-corridor.md](03-dashboard-corridor.md) | 双站摘要、统一线路图和唯一主窗口 |
| 阶段 4 | [04-dual-operations-train.md](04-dual-operations-train.md) | 真实操作按钮、改方/网络和联合列车演示 |
| 阶段 5 | [05-integration-delivery.md](05-integration-delivery.md) | 全量测试、三分辨率视觉验收和最终交付 |

## 固定视觉要求

使用用户参考图左上角“方案一：经典控制台风格”：浅灰白背景、深蓝标题栏、
蓝色选中导航、白色细边框面板、紧凑表格和铁路状态语义色。按钮和设备对象必须
来自当前 CTCS-2 作业要求与软件真实功能，不照抄参考图中的虚构菜单或站场设备。

## 固定工程要求

- 正式工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`。
- 阶段 0 修复 Git 后，开发分支为 `codex/dual-station-dashboard`。
- IDE 如需使用，仅使用 PyCharm。
- 新功能严格测试先行，中文注释、类型标注、模块化边界。
- `docs/IMPLEMENTATION_STATUS.md` 每阶段持续更新，保证中断后可恢复。
- 不自动合并 `main`，不强推，不删除历史代码。

