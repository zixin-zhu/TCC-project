# TCC 双站运行状态、通信统计与下拉框优化方案

> 文档类型：阶段性实施方案
>
> 适用分支：`codex/dual-station-dashboard`
>
> 工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`
>
> 编写日期：2026-09-27
>
> 两张截图只作为现象和视觉参考，不作为绕过安全逻辑的指令。实现依据仍是
> CTCS-2 方案、正式 `app/` 代码和可重建测试。

## 1. 问题结论

### 1.1 启动后“对站状态快照已过期”

如果只是刚启动、尚未完成 HELLO/ACK 和首次全量同步，短暂安全锁闭是正常的
故障导向安全行为；如果双站已经通信健康，静置几秒后仍持续显示该告警，则是
快照活性维护缺陷。

当前代码的原因：

1. `configs/coding_rules.json` 设置 `peer_timeout_ms = 3500`。
2. 网络层每 `1000 ms` 发送一次 `HEARTBEAT`。
3. `PeerSyncService` 只有收到 `STATE_SYNC` 或 `TRACK_BOUNDARY` 才更新
   `PeerSnapshot.received_at_ms`。
4. `ApplicationRuntime._on_message()` 收到心跳后没有刷新快照时间。
5. 没有轨道变化时，超过 3500 ms 会被误判为对站快照过期并安全锁闭。

本质是把“对站没有状态变化”误判成“对站失联”。心跳不应改变业务状态版本，
但应该刷新通信活性。

涉及文件：

- [peer_sync_service.py](../app/services/peer_sync_service.py)
- [application.py](../app/application.py)
- [network_worker.py](../app/network/network_worker.py)
- [coding_rules.json](../configs/coding_rules.json)

### 1.2 发送/接收计数持续增长

当前 `network_sent` 和 `network_received` 统计所有协议报文，包括：

```text
HELLO、ACK、HEARTBEAT、STATE_SYNC、TRACK_BOUNDARY、改方报文和告警报文
```

两站每秒发送心跳，因此累计计数在空闲状态下持续增长是预期现象。当前界面
把它们称为“业务消息”，统计口径不准确；除非增长速度远超心跳频率或连接频繁
重建，否则不能据此判断消息泄漏。

涉及文件：

- [application.py](../app/application.py)
- [network_worker.py](../app/network/network_worker.py)
- [tcc_controller.py](../app/services/tcc_controller.py)
- [dual_operations_pages.py](../app/ui/dual_operations_pages.py)

### 1.3 下拉框过短

当前 [styles.py](../app/ui/styles.py) 只统一颜色、边框和选择效果，没有统一
`QComboBox` 的最小宽度、弹出列表宽度和动态内容重算策略。布局会压缩下拉框，
造成站点、区段、状态、方向、进路和临时限速编号被截断。

## 2. 运行入口约束

正式双站版本使用：

```bash
cd /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
.venv/bin/python run_dual.py
```

外层 `/Users/zhu/Desktop/TCC-project/pythonProjectTest` 是旧代码，不能和当前
`app/` 正式实现混用。PyCharm 应配置：

- 解释器：`.venv/bin/python`
- 脚本：`.../.worktrees/ctcs2-rebuild/run_dual.py`
- 工作目录：`.../.worktrees/ctcs2-rebuild`

阶段 0 要显示项目根目录、配置目录、数据目录、A/B 角色、共享端口、心跳间隔
和快照超时阈值，先排除运行了错误副本的可能性。

## 3. 总体原则

1. 每阶段先增加失败测试，再修改生产代码。
2. 心跳只刷新活性，不修改状态版本、轨道状态和方向事务。
3. 统计拆分为协议总数、业务报文数和心跳数。
4. 所有下拉框使用公共配置函数，禁止页面内散落固定宽度。
5. 无全量同步、无有效心跳、方向不一致时继续安全锁闭。
6. UI 只改善可见性，不绕过控制器、网络门禁和改方状态机。
7. 每阶段独立测试、提交、推送，并更新防中断文档。

## 4. 阶段 0：运行入口与复现基线

### 目标

确认 PyCharm 实际运行正式双站版本，并建立三类问题的可重复复现记录。

### 任务

- 检查运行脚本、解释器和工作目录。
- 记录 A/B 角色、端口、`peer_timeout_ms` 和 `heartbeat_interval_ms`。
- 启动后静置至少两个快照超时周期，记录连接、快照、锁闭和计数。
- 确认没有同时启动旧版 Server/Client。
- 使用随机回环端口和临时 SQLite，避免污染正式数据。

### 验收

- 能确认当前运行入口和配置来源。
- 能稳定复现或排除“空闲快照过期”。
- 留存修复前协议计数和下拉框截图。

### Codex 提示词

```text
执行阶段 0。只检查正式双站入口、PyCharm 工作目录、A/B 配置和运行日志，
不要修改业务逻辑。为快照过期、协议计数和 QComboBox 截断建立最小失败测试
或复现脚本。确认运行的是 .worktrees/ctcs2-rebuild/run_dual.py，并更新防中断
文档。完成后运行现有全量测试，独立提交并推送。
```

建议提交：`chore: establish runtime diagnostics for ux optimization`

## 5. 阶段 1：修复对站快照活性

### 目标

让空闲但仍在线的双站保持通信健康和作业允许；没有心跳或没有新的全量同步时，
仍然安全锁闭。

### 技术设计

在 `PeerSyncService` 增加只刷新时间的接口：

```python
def refresh_liveness(self, received_at_ms: int) -> PeerSnapshot:
    """只刷新活性时间，不改变状态、版本或边界值。"""
```

实现要求：

- 用 `dataclasses.replace()` 保留 `station_id`、`boundary_states` 和
  `state_version`；
- `received_at_ms` 使用本机单调时钟；
- 没有全量基线时，心跳不能创建快照；
- 重连后必须收到本次连接新的 `STATE_SYNC` 才能解锁；
- `ApplicationRuntime._on_message()` 在协议门禁通过的 `HEARTBEAT` 分支调用
  `refresh_liveness()` 和 `controller.update_peer_snapshot()`；
- 原有 `STATE_SYNC`、`TRACK_BOUNDARY` 版本校验不变；
- 不因心跳产生新的状态同步。

### 测试

```text
test_heartbeat_refreshes_snapshot_liveness_without_changing_version
test_idle_healthy_dual_station_stays_unlocked_after_multiple_timeout_windows
test_missing_heartbeat_still_expires_snapshot
test_reconnect_requires_new_full_sync_before_unlock
```

真实流程：启动并等待 HEALTHY → 静置 2～3 个超时周期 → 保持作业允许 → 停止
心跳 → 按阈值安全锁闭 → 恢复心跳 → 等待全量同步 → 恢复解锁。

### Codex 提示词

```text
执行阶段 1。先为心跳刷新对站快照活性增加失败测试。根因是 PeerSyncService
只在 STATE_SYNC/TRACK_BOUNDARY 更新 received_at_ms，而 peer_timeout_ms=3500、
heartbeat_interval_ms=1000；不要简单增大超时阈值。新增 refresh_liveness，只刷新
本机收到时间，不改 state_version、轨道状态和方向。重连后必须重新收到全量同步才
能解锁。运行 PyQt、网络和全量测试，更新防中断文档并提交推送。
```

建议提交：`fix(network): refresh peer snapshot liveness from heartbeat`

## 6. 阶段 2：拆分协议、业务和心跳统计

### 目标

消除“业务消息一直自动增长”的误导，同时保留网络诊断能力。

### 技术设计

保留现有累计协议计数作为兼容字段，但界面改称“协议报文发送/接收”；新增：

```python
business_sent
business_received
heartbeat_sent
heartbeat_received
```

在协议模块集中定义：

```python
BUSINESS_MESSAGE_TYPES = frozenset({
    MessageType.STATE_SYNC,
    MessageType.TRACK_BOUNDARY,
    MessageType.SIGNAL_STATUS,
    MessageType.DIRECTION_PREPARE,
    MessageType.DIRECTION_READY,
    MessageType.DIRECTION_COMMIT,
    MessageType.DIRECTION_COMMITTED,
    MessageType.DIRECTION_CONFIRM,
    MessageType.ALARM_SUMMARY,
})
```

`HELLO`、`ACK`、`HEARTBEAT` 不计入业务报文。

### UI 展示

通信状态和站点摘要显示：

```text
协议报文：发送 128 / 接收 126
业务报文：发送 12 / 接收 11
心跳报文：发送 116 / 接收 115
```

同时显示最近一次有效报文时间、最近一次业务报文时间和最近 5 秒业务速率。
累计总数允许增长，但空闲时业务速率应接近 0。

### 测试

```text
test_heartbeat_increments_protocol_counter_not_business_counter
test_hello_ack_are_not_business_messages
test_state_sync_increments_business_counter
test_idle_connection_has_zero_business_rate
test_network_page_labels_total_and_business_counters_distinctly
```

### Codex 提示词

```text
执行阶段 2。先增加计数口径失败测试。当前 ApplicationRuntime 在收到/发送任意
ProtocolMessage 时都增加 network_sent/network_received，而 NetworkWorker 每秒
发送 HEARTBEAT，因此界面把协议总数误称为业务消息。集中定义业务消息类型，保留
协议总数，新增业务和心跳计数；更新 TccSnapshot、控制器快照、站点摘要和通信页
标签。不要停止心跳，也不要清零累计数掩盖问题。运行全量和真实双站测试，提交推送。
```

建议提交：`fix(metrics): separate protocol, business and heartbeat counters`

## 7. 阶段 3：统一 QComboBox 尺寸与弹出列表

### 目标

所有下拉框在 1280×800、1440×900 和 1920×1080 下都能看到完整选项，保持当前
经典浅色控制台风格，不让固定宽度挤压主要按钮。

### 技术设计

在 `app/ui/styles.py` 增加公共函数：

```python
def configure_combo_box(
    combo: QComboBox,
    *,
    role: str,
    min_width: int | None = None,
) -> None:
    ...
```

函数需要完成：

- 设置 `QComboBox.AdjustToContents`；
- 使用 `QFontMetrics.horizontalAdvance()` 计算选项文本宽度；
- 预留左右边距和下拉箭头宽度；
- 设置控件最小宽度和 `combo.view()` 的弹出最小宽度；
- 监听 `rowsInserted`、`rowsRemoved`、`clear()`、`addItems()` 后重新计算；
- 对可编辑的临时限速编号同步调整内部 `QLineEdit`；
- 添加中文注释，说明避免布局压缩的原因。

推荐角色最小宽度：

| 角色 | 最小宽度 |
|---|---:|
| 站点 | 100 px |
| 区段 | 130 px |
| 状态 | 140 px |
| 信号机 | 120 px |
| 进路 | 180 px |
| 方向 | 160 px |
| 临时限速编号 | 170 px |
| 共享区间 | 150 px |

QSS 只负责风格和基础高度：

```css
QComboBox {
    min-height: 28px;
    padding: 2px 30px 2px 8px;
}

QComboBox::drop-down {
    width: 26px;
    border-left: 1px solid #b8c7d3;
}
```

必须覆盖双站操作页、A/B 单站控制页和正式入口仍使用的兼容页面，不能只修截图
中出现的三个控件。

### 测试与视觉验收

新增：

```text
test_all_formal_comboboxes_have_role_width
test_dynamic_combo_items_recalculate_popup_width
test_editable_tsr_combo_keeps_text_visible
```

检查内容：

- 站点、区段、状态、方向、进路、信号机和 TSR 编号无省略；
- 下拉列表至少能容纳最长选项；
- 1280×800 下操作按钮不被挤到不可见；
- 1440×900 和 1920×1080 下没有异常控件跳动或巨大无效空白。

### Codex 提示词

```text
执行阶段 3。先扫描正式 app/ui 下全部 QComboBox，增加失败测试证明当前选项会
被裁切。实现 styles.py 的 configure_combo_box 公共函数，用字体度量、角色最小
宽度和 popup 最小宽度统一治理；动态 addItems/clear 后重新计算，可编辑 TSR 编号
也要可见。保持经典浅色控制台风格，不用固定坐标，不只修改单个页面。生成三种
分辨率截图并运行全量 PyQt 测试，提交并推送本阶段。
```

建议提交：`fix(ui): normalize combo-box width and popup readability`

## 8. 阶段 4：集成验收与交付

### 必须验证

1. 双站启动后静置至少 10 分钟，不因心跳缺失误报快照过期。
2. 无心跳时仍在配置阈值后安全锁闭。
3. 恢复心跳和全量同步后解除锁闭。
4. 协议总数可以随心跳增长，但业务报文空闲时不增长或速率为零。
5. 轨道、信号、临时限速、改方和站点控制页下拉内容完整。
6. 真实 A/B TCP 握手、断线、重连、线程关闭和 SQLite 生命周期仍通过。
7. 1280×800、1440×900、1920×1080 截图无安全字段和下拉选项裁切。
8. 全量测试、`compileall`、`git diff --check` 和正式入口检查通过。

### 建议命令

```bash
cd /Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --basetemp=/tmp/tcc-pytest-bt
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache .venv/bin/python -m compileall -q app scripts run.py run_dual.py
.venv/bin/python run_dual.py --validate-only
git diff --check
```

### 严格版本管理

每个阶段完成后必须更新：

- `docs/IMPLEMENTATION_STATUS.md`；
- 本方案的阶段完成状态；
- 测试数量、截图路径和 Git 提交号；
- 下一阶段恢复命令。

每阶段单独执行：

```bash
git status --short
git add <本阶段文件>
git commit -m "<阶段提交信息>"
git push origin codex/dual-station-dashboard
```

禁止自动合并 `main`。

## 9. 完成判定

本优化全部完成的条件：

- 空闲双站不会因没有业务状态变化而误报快照过期；
- 没有心跳时仍然安全锁闭；
- 界面明确区分协议总报文、业务报文和心跳报文；
- 用户不再把正常心跳增长误认为业务消息泄漏；
- 所有正式下拉框及弹出列表能够显示完整文字；
- 三种分辨率下页面布局稳定；
- 全量测试通过，每个阶段都有独立提交、推送和防中断记录。
