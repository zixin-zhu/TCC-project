# TCC 项目防中断交接说明

> 本文件与 `docs/tcc-vibe-plans/08-ctcs2-spec-and-ui-train-optimization.md` 配套使用。新代理接管时先读取本文件，再读取方案中标记为“进行中”的阶段；不要重复已经有 commit 和测试证据的阶段。

## 当前工作树

- 项目：CTCS-2 车站列控中心（TCC）A/B 双站教学仿真
- 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
- 分支：`codex/dual-station-dashboard`
- 代码状态：阶段 0～阶段 8 已完成；“公共区段双站确认与控制台优化”和“单站控制页布局重构”阶段已提交并推送
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
- 下一步：若继续开发，先创建新的阶段方案；重新连接后先查看本节和 `git log --oneline -5`

## 2026-09-27 双站本地权威与改方双确认修复（当前阶段）

- 依据：`技术规范/客运专线CTCS-2级列控系统列控中心技术规范暂行的通知.pdf`，以及用户明确的 A/B 双站本地权威、方向动态请求方、双方确认要求。
- 已修改：生产控制器继续让 A/B 各自保存本站运行方向和局部设备状态；A/B Server/Client 只代表 TCP 建链角色，不再决定业务权威。
- 已修改：生产改方状态机在 `authority_station_id=None` 模式下按当前方向起点动态决定请求方（A→B 为 A，B→A 为 B），对站负责本地安全校验和应答；错误站点不能创建事务。
- 已修改：`APPROVE` 只完成预留，申请方收到对站 `ACK` 后才执行本站 `APPLY`；响应方在 `COMMIT` 时执行本站 `APPLY`，双方确认前不形成可放行的共享方向。
- 已修改：A/B 单站控制页和双站区间改方页新增“改方请求处理（双方确认）”板块，显示请求方、应答方、事务号、阶段和双方版本；“复核当前对站请求”只读展示自动安全校验结果，“安全复核并解除锁闭”只能重新执行通信/快照/区段/进路/方向守卫，不能强制清锁。
- 已修改：安全锁闭恢复增加 `TccController.recover_safety_lock()`；无新鲜对站方向、有活动事务、区段/进路条件不满足时继续拒绝并保持锁闭。
- 定向验证：改方、控制器、A/B 请求处理页和双站操作页测试通过。
- 完整验证：`331 passed`，包含真实本机 TCP 握手、双向改方、动态应答方断链恢复和 Qt UI 回归。
- 阶段提交：`37f8e70 fix(ctcs2): enforce bilateral direction authority and recovery`，已推送到 `origin/codex/dual-station-dashboard`。
- 交接下一步：重新连接后先读取本节和最新 `git log`，不要重复改方协议阶段。

## 2026-09-27 公共区段双站确认与控制台优化（进行中）

- 用户修正规则：公共区段人工状态由申请方提交；只要对站确认即可对 A/B 两端同时生效，申请方不能确认自己的申请。
- 新增 `app/services/shared_state_request_service.py`：申请、对站确认、拒绝、双端写入、部分失败补偿、历史记录和 `requests_changed` 信号均集中管理；列车 TRAIN 自动占用链路不接入人工审批。
- A/B 单站控制页新增“公共区段申请确认（A/B 双站）”，包含待处理申请、已处理记录、同意/拒绝按钮；共享状态提示统一为“已提交申请，正在等待 A/B 站确认……”。
- 站点摘要卡最右侧新增“安全复核并解除锁闭”，失败时显示控制器返回的具体原因；方向页原“改方请求处理”视觉板块已删除。
- A/B 单站网络页新增本站网络中断/恢复按钮；协议、业务、心跳计数改为固定宽度分行显示，通信页计数列固定宽度，避免数字增长推动布局。
- 测试证据：新增共享申请事务单测；更新双站 UI/E2E 场景为“提交→对站确认→生效”；当前完整回归 `334 passed`（含真实本机 TCP）。
- 阶段提交：`6aebbe0 feat(ctcs2): add bilateral shared-state confirmation workflow`，已推送到 `origin/codex/dual-station-dashboard`。
- 下一步：重新连接后先执行 `git status --short` 和 `git log --oneline -5`；本阶段无需重复实现，后续需求从新阶段开始。

## 2026-09-27 A/B 控制页布局重构（已完成）

- 依据用户最新界面要求：安全复核按钮位于 A/B 站点摘要卡最上方一行最右侧；公共区段申请确认从“总览拓扑”移出，成为 A/B 控制页独立的“申请处理”页面。
- 双站 `StationDetailWidget` 不再创建“网络”和“区间改方”页签；两部分内容改为“总览拓扑”页中的 `网络`、`区间改方` 两个独立区块。单站旧入口仍保留原九页，避免破坏单站诊断模式。
- 新增布局回归测试，验证页签、区块归属和安全按钮位置；完整测试 `335 passed`。
- 阶段提交：`e3e56c4 refactor(ui): reorganize dual station control pages`，已推送到 `origin/codex/dual-station-dashboard`。
- 下一步：重新连接后读取本节，确认工作区干净，再开始新的 UI/业务阶段。

## 2026-09-27 顶部安全复核与双站申请处理重构（已完成）

- 用户最终界面规则：安全复核按钮只保留一个，固定放在全局顶部状态条最右侧；
  A/B 摘要卡和控制页不再放置重复入口。按钮只在聚合状态安全锁闭时可用，复核
  失败直接在顶部显示控制器返回的具体原因，不绕过安全守卫强制解锁。
- A/B 控制页新增独立“申请处理”页签，位置紧随“总览拓扑”；“网络”和“区间
  改方”仍作为总览页中的两个区块，日志告警保持独立页签。
- 公共区段及方向申请统一由 `SharedStateRequestService` 管理：申请方提交只登记
  事务，不写入实际状态；待处理表只显示对站申请，自己的申请只在对站页面可见。
  每行按“申请编号、时间、申请站、内容、操作”展示，并在操作列提供同意/拒绝。
  对站同意后，公共区段才执行 A/B 双端写入；方向申请则由申请方控制器启动既有
  双站协议事务，仍需通过协议双方安全条件校验。
- 申请内容统一生成两类可读文本：`X站申请将Qx区段状态由旧状态修改为新状态`、
  `X站申请将方向由X_TO_X改为X_TO_X`；提交提示统一为“已提交申请，正在等待
  A/B 站确认……”。
- 演练型“发起改方并立即中断应答方”先登记改方申请，再模拟对站链路中断，恢复
  后仍可回到对站“申请处理”页逐条确认，不会绕过审批直接改方。
- 测试证据：完整回归 `336 passed`，包含真实本机 TCP 握手、断链恢复、A/B UI
  页面顺序、行内审批、动态请求方及重复场景；`git diff --check`、离屏编译检查
  均通过（字节码缓存使用 `/tmp/tcc-pyc`，避免沙箱目录权限干扰）。
- 阶段提交：`6cee11e fix(ui): enforce peer approval and global recovery action`，
  已推送到 `origin/codex/dual-station-dashboard`。
- 下一步：重新连接后先查看本节、`git status --short` 和最新 `git log --oneline -5`，
  不要回退到旧的外置审批按钮方案。

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
- 提交：`38600af fix(startup): complete dual self-check and refresh LEU alarms`，
  已推送到 `origin/codex/dual-station-dashboard`。
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
