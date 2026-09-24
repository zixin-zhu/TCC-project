# TCC CTCS-2 改造防中断上下文

> 此文件随代码提交并在每个阶段更新。重新连接后，先读取本文件、总控方案、当前阶段子方案和 `git log --oneline --decorate -10`，从“下一步”继续，不重复已完成阶段。

## 仓库状态

- 仓库：`git@github.com:zixin-zhu/TCC-project.git`
- 开发分支：`codex/ctcs2-rebuild`
- 基线提交：`d62e396`（Initial version）
- 工作树：`/Users/zhu/Desktop/列控课设/.worktrees/ctcs2-rebuild`
- IDE 约束：如需 IDE，只使用 PyCharm。
- UI 约束：沿用现有界面视觉风格，阶段 6 只重构结构和功能完整性。

## 固定工程约束

1. 一次只完成一个阶段，验收通过后独立提交并推送。
2. 新功能严格执行测试先行；生产代码使用类型标注、模块化边界和必要的详细中文注释。
3. 旧代码在阶段 7 确认无引用前不删除；用户已有修改不得覆盖。
4. JSON/HEX/CRC32 是 `simulation_envelope`，不宣称真实应答器位流或安全通信。
5. CTCS-3 论文只提供架构和教学展示参考，核心业务保持 CTCS-2。

## 环境和已知问题

- 系统 Python：3.9.6；目标方案要求后续提供 Python 3.11/3.12 可重建环境。
- 初始仓库没有测试文件和依赖清单。
- macOS 系统 Python 默认字节码缓存目录受沙箱限制；基线验证使用 `PYTHONPYCACHEPREFIX=/private/tmp/tcc-pycache`。
- 原代码存在两套入口、信号双轨状态、提前改方、网络线程边界等已知问题，详见总控方案。

## 阶段状态

| 阶段 | 状态 | 提交 | 推送 | 验收摘要 |
|---|---|---|---|---|
| 1 工程/配置/领域模型 | 已完成，待提交/推送 | 本阶段 HEAD | 待推送 | 20 项测试；A/B 配置校验通过 |
| 2 编码与点灯 | 未开始 | — | — | — |
| 3 应答器/LEU/限速 | 未开始 | — | — | — |
| 4 双站网络 | 未开始 | — | — | — |
| 5 区间改方 | 未开始 | — | — | — |
| 6 UI/持久化 | 未开始 | — | — | — |
| 7 集成交付 | 未开始 | — | — | — |

## 已完成：阶段 1

完成内容：

- 建立 `app/core` 强类型枚举、配置 dataclass、领域事件和多来源轨道状态。
- 实现站点、拓扑、进路、边界、应答器组、LEU 与默认报文的配置校验。
- 提供 A Server/B Client 正式配置、旧 G01~G08 迁移映射和统一 `run.py`。
- 建立 Python 3.12 `.venv`、pytest、PyQt5 和 Qt 环境诊断。
- 阶段验收：`20 passed`；A/B `--validate-only` 均通过；新代码编译通过。

阶段决定：有效轨道状态不变时不增加 `state_version`，即使较低优先级来源发生变化；这样避免被故障遮蔽的列车输入制造无意义同步版本。

新增环境发现：Qt 5 在包含中文的安装路径中可能把插件路径编码成 `????`。诊断脚本可定位真实插件；正式 GUI 启动的动态插件路径准备留在阶段 6 实现并测试，禁止硬编码用户绝对路径。

## 当前阶段：阶段 2（尚未开始）

下一步：读取阶段 2 子方案和 Task 2 brief；先写进路、正反向编码、边界保护和信号映射失败测试。

## 恢复命令

```bash
cd /Users/zhu/Desktop/列控课设/.worktrees/ctcs2-rebuild
git status --short
git log --oneline --decorate -10
sed -n '1,240p' docs/IMPLEMENTATION_STATUS.md
```
