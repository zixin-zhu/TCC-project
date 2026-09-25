# 双站同屏最终验收记录

验收日期：2026-09-26

分支：`codex/dual-station-dashboard`

推荐入口：`run_dual.py`

## 自动化与真实运行证据

| 验收项 | 结果 | 可重建证据 |
|---|---|---|
| 全量回归 | 通过，`264 passed` | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -p no:cacheprovider -q` |
| 真实双站握手/同步 | 通过 | `test_real_window_handshake_sync_fault_and_reconnect` |
| 真实故障断开/自动重连 | 通过 | 同上；验证通信非健康、锁闭、恢复 HEALTHY、计数增长和双向全量快照 |
| 正向列车/正常改方/反向列车 | 通过 | `test_real_tcp_runtime_runs_forward_changes_direction_and_runs_reverse` |
| 关闭生命周期 | 通过 | `test_close_releases_threads_databases_and_listener_port`；线程/timer 停止、数据库可重开且完整、端口可重绑 |
| 12 页及按钮 | 通过 | `test_all_navigation_pages_are_visible_and_buttons_are_named` |
| 七类课程场景顺序执行与复位 | 通过 | `test_seven_course_scenarios_run_through_real_dual_window_and_reset`；关闭后重开真实 SQLite 核对关键操作日志 |
| A 端口占用 | 通过 | `test_occupied_a_listener_port_prevents_b_start` |
| 关闭超时安全处理 | 通过 | `test_dual_window_rejects_close_when_runtime_stop_times_out`、`test_close_failure_keeps_train_timer_safely_stopped` |

以上真实网络测试均使用操作系统分配的 `127.0.0.1` 随机端口和 `tmp_path`
数据库；不依赖截图中的合成 HEALTHY 状态。

## 七类课程场景

| 场景 | 前置与操作 | 可见结果及持久化/日志证据 | 复位与对应 UI 图（合成布局证据） |
|---|---|---|---|
| 全空闲基线 | 双站 HEALTHY、Q1～Q4 空闲；A 站建立 `A_DEPART` | A 卡片显示活动进路，区段码序/信号同步变化；关闭后 SQLite 包含建立/取消进路 | 取消 `A_DEPART`；[总览](dual-dashboard/synthetic_ui_overview_1280x800.png) |
| 区间占用 | 轨道页选择共享 Q3 并设为占用 | A/B Q3 同时占用，线路和码序降级；SQLite 包含两站 Q3 操作 | Q3 改回空闲；[线路](dual-dashboard/synthetic_ui_corridor_1280x800.png) |
| 轨道故障 | 共享 Q2 设故障占用 | Q2 显示故障占用并输出 HU 保护码；SQLite 包含 Q2 操作 | Q2 改回空闲；[线路](dual-dashboard/synthetic_ui_corridor_1280x800.png) |
| 红灯灯丝故障 | 先使 Q1 输出 HU，再在信号页选择 A/SA 并勾选故障 | 显示 `RED_LAMP_FAILURE`、严重告警、HJ/UJ/LJ 落下；SQLite 包含 SA 设置 | 清灯丝故障并清 Q1；[总览](dual-dashboard/synthetic_ui_overview_1280x800.png) |
| 临时限速 | A 站预存并执行合法 `TSR-E2E` | TSR 为 ACTIVE，LEU 选择限速逻辑报文；SQLite 包含预存/执行/撤销 | 撤销 TSR；[总览](dual-dashboard/synthetic_ui_overview_1280x800.png) |
| 正常改方 | 区间空闲、无进路、双站 HEALTHY；A 申请 B→A | 真实 TCP 四阶段事务完成，A/B 为 B_TO_A 并解锁；SQLite 包含申请记录及 A 权威方向 | 下一场景请求改回；[改方](dual-dashboard/synthetic_ui_direction_1280x800.png) |
| 改方中断线 | 点击“发起改方并立即中断B站” | 通信非健康、相关作业锁闭、信号保护；恢复后计数增长、双向边界快照完整 | 通信页恢复 B，等待 HEALTHY、方向一致并解锁；[网络](dual-dashboard/synthetic_ui_network_1280x800.png) |

上述七项由同一个真实 TCP 双站窗口测试顺序执行，每一步断言界面背后的正式
控制器快照，最后检查 Q1/Q2/Q3 空闲、无进路、方向一致和联合解锁；窗口关闭后
重新连接 A 站 SQLite，逐项核对进路、轨道、灯丝、限速和改方日志。对应图片
只作为布局定位，不冒充该次真实测试截图。七个场景的导航、真实按钮名称、
详细步骤与复位顺序还由
`app/services/demo_scenarios.py` 固化，并由
`test_delivery_catalog_contains_seven_complete_scenarios`、
`test_every_scenario_control_object_exists_in_dual_window` 防止文档与 UI 漂移。

## 四类工程场景

| 场景 | 注入方式 | 安全结果 | 复位结果 |
|---|---|---|---|
| 正反向联合列车 | 建立相应发车进路后运行 A→B，正常改方，再运行 B→A | 唯一协调器按拓扑占用；到达后状态可验证 | 两次均可复位，真实 TCP 测试通过 |
| 共享输入部分失败 | 模拟 A 成功、B 写入失败，含 CLEAR 失败 | 严重告警；CLEAR 部分失败会在 A 侧恢复保守占用 | 故障移除后双站重写一致；四项 `test_shared_track_input` 回归通过 |
| A 监听端口占用 | 预占配置端口后启动双运行时 | A 启动失败可见，B 不启动，联合操作保持锁闭 | 关闭占用 socket 后端口可重新使用 |
| 关闭等待超时 | 运行时返回停止超时 | 窗口拒绝关闭并显示原因；列车 timer 保持停止 | 后续成功 stop 可重试；生命周期回归通过 |

## 视觉证据

1280×800、1440×900、1920×1080 的总览、线路、改方、网络和列车页共
15 张合成 UI 截图及检查结果见
[DUAL_STATION_UI_ACCEPTANCE.md](DUAL_STATION_UI_ACCEPTANCE.md)。图片明确标注
“仅用于 UI 视觉验收”，真实通信证据见上文自动化测试。

## 教学边界与结论

- 本软件是 CTCS-2 课程仿真，未实现现场安全计算机、冗余硬件、铁路安全通信
  或安全认证，不得用于真实铁路控制。
- JSON、HEX、CRC32 与教学位流属于 `simulation_envelope`，不冒充真实
  1023 位应答器报文。
- 单进程双站同屏仍由两个独立运行时通过真实 TCP 交换信息；单站与多进程入口
  仅保留用于诊断。

结论：第五阶段自动化、真实运行、生命周期、工程故障和视觉验收通过；最终
独立复审无 Critical/Important，配置、编译、差异和正式包边界检查均通过，
待 Git 提交推送后形成交付检查点。
