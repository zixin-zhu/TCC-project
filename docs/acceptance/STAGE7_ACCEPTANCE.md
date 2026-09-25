# 阶段 7 集成交付验收记录

- 验收日期：2026-09-25（Asia/Shanghai）
- 分支：`codex/ctcs2-rebuild`
- 阶段 6 基线：`5f8ff57`
- Python：项目 `.venv`（Python 3.12）

## 自动验证

| 项目 | 命令/方法 | 结果 |
|---|---|---|
| 全量测试 | `.venv/bin/python -m pytest -q` | `196 passed` |
| A 配置 | `.venv/bin/python run.py --station A --validate-only` | 通过，SERVER |
| B 配置 | `.venv/bin/python run.py --station B --validate-only` | 通过，CLIENT |
| 编译 | `python -m compileall -q app scripts run.py main.py run_new_ui.py` | 通过 |
| 差异格式 | `git diff --check` | 通过 |
| 旧包引用 | `rg` 扫描正式包、入口、脚本与测试 | 无顶层旧包导入 |

全量测试包括真实本机回环 socket 的握手、状态同步、延迟启动、重连、退避和
Qt 网络线程关闭。新增列车测试验证正反方向拓扑顺序、只写 `TRAIN` 来源以及
列车出清/复位不删除人工或故障来源。

## 双站进程演练

执行：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/launch_two_stations.py
```

结果：A、B 两个正式窗口均成功创建；本次 A 的网络线程在 `bind + listen`
成功后发布一次性就绪凭据，启动器据此启动 B；持续运行期间无
协议/线程异常。按 `Ctrl+C` 后启动器返回 130 并统一终止子进程，无子进程
`KeyboardInterrupt` 回溯。运行数据库生成于 `data/A/tcc_a.db`、
`data/B/tcc_b.db`，未纳入版本库。

## 界面证据

- [A 站正式总览](screenshots/station_a_overview.png)
- [B 站正式总览](screenshots/station_b_overview.png)

截图由 `scripts/capture_acceptance_screenshots.py` 使用正式控制器和窗口离屏生成。
为稳定复现界面，它会注入合成的 `HEALTHY`、对站快照和权威方向，因此截图只
作为 UI 外观与信息布局证据，不作为真实双站握手或同步证据；后者由上节实际
双进程演练和自动集成测试证明。截图已目视检查站点身份、SERVER/CLIENT 角色、
配置化 Q1～Q4、码序、九个功能页和原蓝灰界面风格。可用以下命令重复生成：

```bash
QT_QPA_PLATFORM=offscreen \
  .venv/bin/python scripts/capture_acceptance_screenshots.py
```

## 七类场景证据索引

七类场景的前置条件、步骤、预期和复位见
[`docs/DELIVERY_SCENARIOS.md`](../DELIVERY_SCENARIOS.md)。对应自动证据分布如下：

- 全空闲/区间占用/轨道故障：`test_track_circuit.py`、`test_tcc_controller.py`。
- 灯丝故障：`test_signal_control.py`、正式 UI 交互测试。
- 临时限速与三条报文路径：`test_temporary_speed.py`、`test_leu_selection.py`、黄金报文测试。
- 正常改方/掉线恢复：`test_direction_change.py` 与双端集成测试。
- 列车跨区和来源隔离：`test_train_demo_service.py`。

## 交付边界

当前无已知 P0/P1 缺陷。课程仿真仍不包含真实应答器 1023 位编码、铁路安全
通信认证、硬件冗余、真实联锁接口、车载 ATP 或精确列车制动模型；这些边界已
同时写入 README、界面列车页和报文页，不得在答辩中表述为现场安全系统。
