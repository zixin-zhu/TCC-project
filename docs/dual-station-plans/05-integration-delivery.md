# 阶段 5：集成验收、视觉校准与最终交付 Implementation Plan（实施方案）

> **给执行 Codex：** 使用 `superpowers:executing-plans`、`requesting-code-review` 和 `verification-before-completion`；不得以截图代替真实功能证据。

**目标：** 对单界面双站系统完成自动化、真实运行、视觉和答辩场景验收，形成可重建交付物。

**架构：** 不新增业务功能；只修复验收问题、补齐证据、入口和文档，并保留单站及多进程诊断工具。

**技术栈：** pytest、pytest-qt、PyQt5 离屏渲染、SQLite、Git。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束与复审重点

- 推荐入口是 `run_dual.py`，单站与多进程入口仍可诊断。
- 合成截图必须标注；真实握手必须有独立日志/测试证据。
- 1280×800 不隐藏安全信息，高分辨率不出现大片无效空白。
- 关闭后无 QThread、socket、timer、SQLite 泄漏。
- README 不得包含旧“列控课设”绝对路径。

## 任务 1：端到端自动验收

**文件：** 新建 `tests/integration/test_dual_station_end_to_end.py`、`tests/integration/test_dual_window_lifecycle.py`。

- [ ] 用随机回环端口和 `tmp_path` 启动真实 A/B，验证 HELLO/ACK、HEALTHY、全量同步和计数增长。
- [ ] 验证 A 监听失败、B 延迟启动、B 断线重连、方向不一致、共享区段不一致和关闭超时。
- [ ] 验证关闭后两个线程均停止、数据库可重新打开、端口可重新绑定。
- [ ] pytest-qt 遍历 12 个导航页，断言可见按钮文字非空且操作产生状态或明确拒绝。

## 任务 2：三分辨率视觉验收

**文件：** 新建 `scripts/capture_dual_dashboard.py`、`docs/acceptance/DUAL_STATION_UI_ACCEPTANCE.md`。

- [ ] 在 1280×800、1440×900、1920×1080 各生成总览、线路、改方/网络、列车页截图。
- [ ] 对照方案一检查浅色控制台、蓝色标题/导航、白色细边框面板、紧凑表格、语义色和文字辅助。
- [ ] 检查 A/B 角色与连接、方向、锁闭、告警、区段/码序、信号、LEU、限速、列车和网络计数无裁切。
- [ ] 合成状态截图标注“仅 UI 证据”；真实运行截图不得人工注入 HEALTHY。

## 任务 3：场景与故障演练

- [ ] 执行全空闲、区间占用、轨道故障、灯丝故障、临时限速、正常改方、改方掉线七场景。
- [ ] 追加正反向联合列车、共享输入部分失败、A 端口占用、关闭超时四项工程场景。
- [ ] 每项记录前置、操作、可见结果、日志/数据库证据、复位结果和截图路径。
- [ ] 任一场景不能干净复位则不得交付。

## 任务 4：完善交付文档

**文件：** 修改 `README.md`、`docs/IMPLEMENTATION_STATUS.md`；新建 `docs/acceptance/DUAL_STATION_FINAL_ACCEPTANCE.md`。

- [ ] README 写明 Python 3.12 重建、PyCharm 解释器、Qt 诊断、dual/single/multiprocess 入口和测试命令。
- [ ] 说明单进程两站仍通过真实 TCP 通信。
- [ ] 保留 CTCS-2 教学边界、simulation_envelope、非真实 1023 位报文和非安全认证声明。
- [ ] 防中断文档记录六阶段提交号、最终测试数、分支、工作树、截图、限制和恢复命令。

## 任务 5：最终验证与版本管理

- [ ] 从重建环境执行：

```bash
.venv/bin/python run_dual.py --validate-only
.venv/bin/python run.py --station A --validate-only
.venv/bin/python run.py --station B --validate-only
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app scripts run.py run_dual.py main.py run_new_ui.py
git diff --check
```

- [ ] 实际运行 `run_dual.py` 至 HEALTHY，执行一个正常和一个故障场景后关闭，终端无回溯。
- [ ] 扫描正式包不得导入 `legacy`，数据库和临时截图不得误入 Git。
- [ ] 独立代码复审与整体验收均无 Critical/Important 后提交：

```bash
git add README.md docs scripts tests app
git commit -m "docs: complete dual-station dashboard delivery"
git push origin codex/dual-station-dashboard
```

- [ ] 再提交防中断最终检查点；不自动合并 `main`，等待用户确认。

## 验收门

全量测试零失败；真实双站健康；七类课程场景和四类工程场景通过；三分辨率 UI 清晰；无资源泄漏；远端与本地 HEAD 一致；无 Critical/Important。

## Codex 执行提示词

```text
执行双站同屏阶段 5。读设计基线、全部阶段检查点、本文件和 DELIVERY_SCENARIOS。不要新增范围外功能。建立真实端到端与关闭生命周期测试，按 1280×800/1440×900/1920×1080 校准参考图方案一的经典控制台视觉，完整演练七类课程场景和四类工程故障。截图必须区分合成 UI 证据与真实握手证据。更新 README、防中断和最终验收记录，运行完整 pytest/compile/config/diff 验证，独立复审无 Critical/Important 后提交推送；禁止自行合并 main。
```
