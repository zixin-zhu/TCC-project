# UX 可用性修复防中断上下文（BugFix 阶段）

> 目的：修复用户反馈的「界面操作不可用 / 体验不一致」类问题。本文件是本次修复任务的
> 防中断账本。**重新连接后，先读本文件 + `git log --oneline -10`，从「下一步」继续。**

## 仓库状态

- 仓库：`git@github.com:zixin-zhu/TCC-project.git`
- 当前分支：`codex/dual-station-dashboard`
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 进入本任务前 git 干净，HEAD=`37a65e6`，全量回归 `264 passed`。
- 本任务是主仓库之外的增量修复，不改写已完成的双站改造历史；每修完一批独立提交。

## 用户额外要求（本次必须遵守）

1. 每个阶段性任务完成后，用 git 进行严格规范的版本管理与上传。
2. 代码规范化、模块化，新增/修改处必须有详细中文注释。
3. 持续维护本防中断文档：网络波动/额度不足重新连接后，据此继续，不重复已完成部分。
4. 测试先行：每个修复先补失败测试，再改代码，跑全量回归确认全绿后提交。

## 六个待修复问题（均可复现/已确认）

| # | 问题 | 定位 | 修复要点 | 状态 |
|---|---|---|---|---|
| 1 | 列车页锁闭时「暂停/复位」仍可点 | `app/ui/dual_operations_pages.py` `TrainOperationsPage.set_snapshot`(~771) | `pause_button` `reset_button` 随 `available` 一并禁用 | ✅ 已修复 |
| 2 | 单站控制页列车按钮锁定不一致 | `app/ui/station_detail_widget.py` `_update_action_enabled`(368-370) | `create/dispatch/start/pause/reset` 五个列车按钮随全局锁一致禁用 | ✅ 已修复 |
| 3 | 共享区段只改一站全局锁闭但无具体预警 | `app/ui/dual_snapshot.py`、`global_status_bar.py`、`dual_main_window.py` | 聚合器新增 `lock_reason`；状态条 tooltip 与操作结果栏显示具体原因 | ✅ 已修复 |
| 4 | 信号灯丝数据显示格式不统一 | `station_summary_card.py`、`station_detail_widget.py`、`dual_operations_pages.py` | 新增 `styles.relay_text()`，三处统一为 1/0 | ✅ 已修复 |
| 5 | 关闭失败时无弹窗提示 | `dual_main_window.py` closeEvent | 抽出 `_notify_close_failed()`，关闭失败弹 `QMessageBox` 提示；窗口拒绝关闭 | ✅ 已修复 |
| 6 | 线路图对空应答器组越界风险 | `corridor_overview_widget.py` `_draw_balises` | 空 balise 组跳过绘制，避免 `balises[0]` IndexError | ✅ 已修复 |

## 测试先行清单（新增失败测试）

- [x] `tests/unit/test_ui_operation_gating.py`：列车页锁闭时 pause/reset 一致禁用（问题1）
- [x] `tests/unit/test_ui_operation_gating.py`：单站控制页列车按钮锁定时一致禁用（问题2）
- [x] `tests/unit/test_ui_operation_gating.py`：关闭失败时窗口拒绝关闭并给出提示（问题5）
- [x] `tests/unit/test_ui_operation_gating.py`：空应答器组不越界（问题6）
- [x] `tests/unit/test_dual_snapshot.py`：`lock_reason` 在共享不一致/通信/方向时正确（问题3）
- [x] `tests/unit/test_ui_styles.py`：`relay_text` 统一输出 1/0（问题4）

## 当前进度与下一步

- 6 个问题**代码修复与定向测试均已通过**（新增 8 项测试）。
- **全量回归 272 passed（17s）**。关键：本 CodeBuddy 沙箱有两个坑需规避：
  1. **pytest 临时目录**：须用 `--basetemp=/tmp/tcc-pytest-bt`（默认 `pytest-of-*` 根目录
     在沙箱下 mkdir 会报 EEXIST 错误）。
  2. **问题5弹窗阻塞**：关闭失败的模态弹窗必须被测试用 `monkeypatch` 抑制
     （既有集成测试 `test_dual_main_window.py` 已适配）。
- 下一步：
  1. `git add -A` 之后分两批提交并推送（见下）。
  2. 更新 `docs/IMPLEMENTATION_STATUS.md` 追加 UX 修复账本。

## 提交规划

承接既有 12 阶段，新增 2 个提交（先测试后功能，语义清晰）并推送：
1. `test(ui): add regression tests for six UX consistency fixes`
2. `fix(ui): resolve six UX consistency issues (button gating / lock warning / relay format / close prompt / empty balise group)`
推送至 `origin/codex/dual-station-dashboard`。

## 恢复命令

```bash
cd /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
git status --short
git log --oneline --decorate -10
sed -n '1,160p' docs/UX-BUGFIX_PLAN.md
# 全量回归（务必带 --basetemp 规避沙箱临时目录缺陷）
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q --basetemp=/tmp/tcc-pytest-bt
```
