# TCC 项目防中断交接说明

> 本文件与 `docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md` 配套使用。新代理接管时先读取本文件，再读取方案中标记为“进行中”的阶段；不要重复已经有 commit 和测试证据的阶段。

## 当前工作树

- 项目：CTCS-2 车站列控中心（TCC）A/B 双站教学仿真
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 分支：`codex/dual-station-dashboard`
- 代码状态：阶段 0～阶段 8 已完成；工作区干净，远端已同步
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
7. 阶段 6～7：实现 A/B 日志页及页面集成（阶段 6、7 已完成）；
8. 阶段 8：按规范场景做全量验收和交付（已完成）。

## 最近一次阶段记录

- 阶段：8
- 状态：已完成
- 代码提交：待提交（阶段 8 交付证据）
- 推送分支：`origin/codex/dual-station-dashboard`
- 定向测试：规范矩阵 3 项通过；完整规范/真实 TCP/UI 回归共 321 项通过
- 全量测试：`321 passed in 7.78s`（允许本机回环端口）
- 产物：`CTCS2_SPEC_ACCEPTANCE.md`、更新后的答辩场景/README、18 张三分辨率合成截图、规范矩阵测试
- 关键语义：A/B 各自维护本站局部权威；Server/Client 只表示 TCP 建链顺序；规范边界、2D 列车、A/B 日志和三类断链入口均有可重建证据
- 下一步：本轮方案完成；若继续开发，先创建新的阶段方案，不要在无新验收门槛时直接修改已交付功能

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
