# 阶段 0：工作区与 Git 恢复 Implementation Plan（实施方案）

> **给执行 Codex：** 必须使用 `superpowers:executing-plans` 逐项执行；每一步完成后勾选。本阶段涉及 Git 元数据，任何实际写入前必须再次向用户说明风险，不得运行 `git init`、`git reset --hard` 或删除 `.git`。

**目标：** 在不丢失提交、分支和未提交方案文档的前提下，修复目录改名造成的 worktree 指针失效，并建立双站同屏专用开发分支。

**架构：** 主仓库仍是 `/Users/zhu/Desktop/TCC-project/pythonProjectTest/.git`，正式代码仍是该仓库的 linked worktree。只修复双方记录的绝对路径，不重新创建仓库。

**技术栈：** Git linked worktree、zsh、pytest、Python 3.12。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束

- 预期阶段 7 HEAD 为 `5a8e06e`，分支为 `codex/ctcs2-rebuild`。
- 所有命令从新路径执行；文档里的旧恢复路径必须改为 `/Users/zhu/Desktop/TCC-project`。
- 先读取、备份两个小型指针文件，再用 `apply_patch` 修改；不得批量改 `.git` 数据库。
- 基线全量测试预期为 `196 passed`；回环网络测试需要本机端口权限。
- 本阶段完成后创建 `codex/dual-station-dashboard`，不直接在阶段 7 分支开发。

## 复审重点

- 新路径中存在同名旧项目时不能修到错误 `.git`。
- 修复后 HEAD、索引和工作树文件必须保持原状。
- 两侧指针必须互相指向，不能只改 worktree 的 `.git`。
- 新增设计/阶段文档必须保留为未提交变更并纳入本阶段提交。
- 远端只推新分支，不强推、不改写 `main`。

## 任务 1：只读确认和备份

- [ ] 运行以下命令，确认两个文件的旧值与设计基线一致：

```bash
sed -n '1,20p' /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild/.git
sed -n '1,20p' /Users/zhu/Desktop/TCC-project/pythonProjectTest/.git/worktrees/ctcs2-rebuild/gitdir
sed -n '1,20p' /Users/zhu/Desktop/TCC-project/pythonProjectTest/.git/worktrees/ctcs2-rebuild/HEAD
```

预期分别包含旧“列控课设”路径和 `refs/heads/codex/ctcs2-rebuild`。若不一致，停止并报告实际内容。

- [ ] 将两个指针文件复制到 `/private/tmp/tcc-worktree-pointer-backup/`，只作本次恢复备份，不复制索引或对象库。

## 任务 2：修复双向指针

**修改：**

- `/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild/.git`
- `/Users/zhu/Desktop/TCC-project/pythonProjectTest/.git/worktrees/ctcs2-rebuild/gitdir`

- [ ] 将 worktree `.git` 的唯一一行改为：

```text
gitdir: /Users/zhu/Desktop/TCC-project/pythonProjectTest/.git/worktrees/ctcs2-rebuild
```

- [ ] 将管理目录 `gitdir` 的唯一一行改为：

```text
/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild/.git
```

- [ ] 验证仓库身份：

```bash
git -C /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild rev-parse --show-toplevel
git -C /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild symbolic-ref --short HEAD
git -C /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild rev-parse --short HEAD
git -C /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild status --short
```

预期：根目录为新 worktree，分支 `codex/ctcs2-rebuild`，HEAD `5a8e06e`；状态仅包含本轮新方案文档。

## 任务 3：建立新分支并修正文档路径

**修改：** `docs/IMPLEMENTATION_STATUS.md`

- [ ] 创建分支：

```bash
git switch -c codex/dual-station-dashboard
```

- [ ] 在防中断文档新增“双站同屏改造”章节，记录新工作区、新分支、设计基线、当前阶段和下一步；把恢复命令中的旧路径全部替换为新路径。

- [ ] 运行路径残留检查：

```bash
rg -n '/Users/zhu/Desktop/列控课设' README.md docs scripts app run.py
```

只允许历史验收记录中明确标注为“旧路径”的文字存在，其余改为新路径。

## 任务 4：基线验证与版本检查点

- [ ] 运行配置和测试：

```bash
.venv/bin/python run.py --station A --validate-only
.venv/bin/python run.py --station B --validate-only
.venv/bin/python -m pytest -q
git diff --check
```

预期 A=SERVER、B=CLIENT、全量 `196 passed`、差异检查零输出。

- [ ] 提交设计基线、六份阶段方案和状态文档：

```bash
git add docs/dual-station-plans docs/IMPLEMENTATION_STATUS.md docs/EXECUTION_PLAN.md
git commit -m "docs: add dual-station dashboard phased plans"
git push -u origin codex/dual-station-dashboard
```

- [ ] 独立复审确认无意外代码变化、无丢失提交、无 Critical/Important 后，更新防中断文档并提交、推送阶段 0 检查点：

```bash
git add docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: record dual-station phase zero checkpoint"
git push origin codex/dual-station-dashboard
```

## 验收门

- Git 状态、日志、分支和远端操作恢复正常。
- `main` 与 `codex/ctcs2-rebuild` 未被改写。
- 196 项基线测试通过。
- 新分支和全部方案已推送；工作树干净。

## Codex 执行提示词

```text
执行双站同屏阶段 0。先读 00-dual-station-design-spec.md 和本文件。当前仅因父目录改名导致 linked worktree 两侧绝对路径失效；禁止 git init、reset、删除 .git 或重新复制仓库。先只读确认并备份两个指针文件，再精确改为 TCC-project 新路径，验证 HEAD=5a8e06e 和分支 codex/ctcs2-rebuild。创建 codex/dual-station-dashboard，更新防中断路径，运行 A/B 配置和 196 项基线测试。复审后提交并推送阶段检查点。
```
