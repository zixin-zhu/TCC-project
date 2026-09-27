# TCC 项目防中断交接说明

> 本文件与 `docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md` 配套使用。新代理接管时先读取本文件，再读取方案中标记为“进行中”的阶段；不要重复已经有 commit 和测试证据的阶段。

## 当前工作树

- 项目：CTCS-2 车站列控中心（TCC）A/B 双站教学仿真
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 分支：`codex/dual-station-dashboard`
- 代码状态：阶段 0～阶段 8 已完成；已完成启动自检/LEU 告警修复，待本次提交推送
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
- 代码提交：`c2d4ee0 docs: record ctcs2 specification acceptance evidence`
- 推送分支：`origin/codex/dual-station-dashboard`
- 定向测试：规范矩阵 3 项通过；完整规范/真实 TCP/UI 回归共 321 项通过
- 全量测试：`321 passed in 7.78s`（允许本机回环端口）
- 产物：`CTCS2_SPEC_ACCEPTANCE.md`、更新后的答辩场景/README、18 张三分辨率合成截图、规范矩阵测试
- 关键语义：A/B 各自维护本站局部权威；Server/Client 只表示 TCP 建链顺序；规范边界、2D 列车、A/B 日志和三类断链入口均有可重建证据
- 下一步：完成本次启动自检/LEU 告警 bugfix 提交并推送；重新连接后先查看本节和 `git log --oneline -5`

## 2026-09-27 启动自检与 LEU 初始告警修复

- 根因 1：`DualStationApplication.start()` 只调用 `begin_startup()`，没有消费 A/B
  `state_changed` 健康事件，因此聚合 `InterfaceStatusService` 永远停在 8 项
  `INITIALIZING`。
- 修复 1：监听 A/B 协议状态；两站均完成 HELLO/ACK 后，严格按
  `StartupStep` 顺序记录 7 项通过，并把 P/V/W 标记为健康。启动完成后的 U
  断链显示为“接口：N 项断开”，不会再次伪装成“启动自检中”。
- 根因 2：控制器首次断链启动时按 fail-safe 安全锁闭并回落 LEU 默认报文；
  告警去重键只按“码+来源”，后续恢复成“无匹配正常报文”时会遗留旧的
  CRITICAL 文本“方向或进路处于安全锁闭”。
- 修复 2：无对端状态基线的初始安全回落不生成持续 LEU 严重活动告警；真实
  断链/已有基线的默认回落仍告警。LEU 同一来源的原因或等级变化时替换旧
  告警记录，避免过期严重文本残留。
- 回归证据：新增启动自检、运行中断链、LEU 告警语义刷新和真实双站断言；
  `325 passed`，包含本机回环 TCP 握手、断链和恢复测试。
- 风险边界：安全锁闭本身没有解除，界面仍显示作业锁闭和通信状态；本修复只
  修正启动诊断生命周期和告警语义，不把默认报文伪装成正常报文发送。

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
