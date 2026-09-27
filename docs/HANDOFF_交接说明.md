# TCC 项目防中断交接说明

> 本文件与 `docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md` 配套使用。新代理接管时先读取本文件，再读取方案中标记为“进行中”的阶段；不要重复已经有 commit 和测试证据的阶段。

## 当前工作树

- 项目：CTCS-2 车站列控中心（TCC）A/B 双站教学仿真
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 分支：`codex/dual-station-dashboard`
- 代码状态：阶段 0、阶段 1 已完成；当前等待阶段 1 提交并推送后的回归确认
- 方案：`docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md`

## 本次方案已覆盖

1. CTCS-2 规范正文、接口、设备配置、RAMS 和附录 1～3 的软件映射；
2. A/B 双站本地权威状态、站间方向/闭塞和失联保持；
3. 轨道正常占用、故障占用、分路不良、HU 防护和编码离线；
4. 应答器/LEU 报文选择、20% 存储余量、默认报文和临时限速六等级；
5. P/Q/R/S/T/U/V/W 接口状态、启动自检和诊断教学模型；
6. 列车 2D 线路可视化、列车选择下拉框、单列车复位后再次发车；
7. A/B 上下分区、逐条显示的日志告警页；
8. 分阶段测试、验收、提交、推送和中断恢复步骤。

## 下一步执行顺序

1. 阶段 0：建立 `docs/ctcs2-spec-traceability.md` 和基线测试，不改业务代码；
2. 阶段 1：双站本地权威状态和方向事务（已完成）；
3. 阶段 2～4：实现 CTCS-2 状态/编码/报文/接口/诊断；
4. 阶段 5：实现列车 2D 场景和可重复生命周期；
5. 阶段 6～7：实现 A/B 日志页及页面集成；
6. 阶段 8：按规范场景做全量验收和交付。

## 最近一次阶段记录

- 阶段：1
- 状态：已完成，待提交推送
- 定向测试：本地权威/一致性/方向/同步/运行时共 52 passed；控制器与方向服务 34 passed
- 全量测试：阶段回归需在允许本机回环端口的环境运行；普通沙箱的 4 项 TCP 测试仅因 `PermissionError` 未能绑定临时端口
- 产物：`LocalAuthorityState`、`InterstationAgreement`、对称改方模式、站间元数据同步、方向复核接口
- 关键语义：A/B 各自持有本站方向和设备状态；A Server/B Client 只表示建链角色；全量同步方向不直接覆盖本地，方向不一致保持安全锁闭
- 下一步：完成阶段 1 全量回归、提交并推送，然后进入阶段 2 轨道状态/编码/信号防护

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
