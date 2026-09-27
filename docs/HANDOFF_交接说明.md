# TCC 项目防中断交接说明

> 本文件与 `docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md` 配套使用。新代理接管时先读取本文件，再读取方案中标记为“进行中”的阶段；不要重复已经有 commit 和测试证据的阶段。

## 当前工作树

- 项目：CTCS-2 车站列控中心（TCC）A/B 双站教学仿真
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 分支：`codex/dual-station-dashboard`
- 代码状态：阶段 0～阶段 6 已完成；工作区干净，远端已同步
- 方案：`docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md`

## 本次方案已覆盖

1. CTCS-2 规范正文、接口、设备配置、RAMS 和附录 1～3 的软件映射；
2. A/B 双站本地权威状态、站间方向/闭塞和失联保持；
3. 轨道正常占用、故障占用、分路不良、HU 防护和编码离线；
4. 应答器/LEU 报文选择、20% 存储余量、默认报文和临时限速六等级；
5. P/Q/R/S/T/U/V/W 接口状态、启动自检和诊断教学模型；
6. 列车 2D 线路可视化、列车选择下拉框、单列车复位后再次发车（阶段 5 已完成）；
7. A/B 上下分区、逐条显示的日志告警页（阶段 6 已完成）；
8. 分阶段测试、验收、提交、推送和中断恢复步骤。

## 下一步执行顺序

1. 阶段 0：建立 `docs/ctcs2-spec-traceability.md` 和基线测试，不改业务代码；
2. 阶段 1：双站本地权威状态和方向事务（已完成）；
3. 阶段 2：轨道状态、编码、信号点灯和附录 1 防护（已完成）；
4. 阶段 3：应答器/LEU、临时限速和断链保持（已完成）；
5. 阶段 4：接口状态、启动自检和诊断教学模型（已完成）；
6. 阶段 5：实现列车 2D 场景和可重复生命周期（已完成）；
7. 阶段 6～7：实现 A/B 日志页及页面集成（阶段 6 已完成，阶段 7 未开始）；
8. 阶段 8：按规范场景做全量验收和交付。

## 最近一次阶段记录

- 阶段：6
- 状态：已完成
- 代码提交：`aa366d3 feat(ui): split station logs and alarms into row-based panels`
- 推送分支：`origin/codex/dual-station-dashboard`
- 定向测试：日志页、告警历史、控制器和双站主窗口共 30 项通过（真实 TCP 另纳入全量）
- 全量测试：`316 passed in 8.05s`（允许本机回环端口）
- 产物：`TccSnapshot.alarm_history`、`LogAlarmRow`、`DualLogAlarmPage`，A/B 上下表格、逐条操作/告警/恢复事件、每站 200 条上限
- 关键语义：活动/已恢复状态用文字表达；告警恢复时间优先使用 `cleared_at_ms`；未把心跳活性刷新写入业务日志；长说明保留 tooltip
- 下一步：阶段 7，组合页面、统一下拉宽度和交互门禁；开始前重新读取本文件、总控方案和阶段 7 小节

## 固定验证命令

```bash
cd /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
rm -rf /tmp/tcc-pytest-bt
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q --basetemp=/tmp/tcc-pytest-bt
```

## 阶段完成记录模板

```text
阶段：
状态：未开始 / 进行中 / 已完成 / 阻塞
代码提交：
推送分支：
定向测试：
全量测试：
截图/日志证据：
遗留问题：
下一步：
```
