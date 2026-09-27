# CTCS-2 规范场景验收记录

验收日期：2026-09-27  
分支：`codex/dual-station-dashboard`  
工作树：`/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild`

本记录用于课程设计软件验收，不是现场铁路设备鉴定。JSON、HEX、CRC32、教学位流
均属于 `simulation_envelope`；2 乘 2 取 2、SIL4、MTBF、物理冗余和安全通信只在
教学诊断模型中表达，不宣称 Python/Qt 达到现场安全等级。

## 自动化证据

```bash
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/tcc-pytest-bt
```

阶段 8 新增规范矩阵测试 3 项通过；阶段 0～7 全量回归在允许本机回环 TCP 端口的
环境中最终为 `321 passed in 7.78s`。普通受限沙箱
禁止绑定临时端口时，真实 TCP 用例会得到 `PermissionError`，这属于环境限制，不
替代业务失败证据。

## 规范要求与证据矩阵

| 范围 | 软件证据 | 场景/测试 |
|---|---|---|
| 双站身份与接口 | A/B 独立配置、P/Q/R/S/T/U/V/W 状态模型、启动自检顺序 | `test_ctcs2_spec_scenarios.py`、`test_startup_self_check.py` |
| 本地权威与站间确认 | A/B 本地轨道/信号/进路/LEU 状态，方向事务双方复核 | `test_local_authority_state.py`、`test_interstation_agreement.py`、改方集成测试 |
| 轨道占用/故障/分路不良 | `FAULT_OCCUPIED`、`SHUNT_BAD`、HU 防护、顺序出清、编码离线红灯 | `test_track_protection_cases.py`、七类场景中的轨道故障 |
| 区间信号与进路 | 进路前置条件由控制器判断，信号由码序/继电器/防护结果导出 | `test_signal_control.py`、`test_route_control.py`、`all-clear`/`red-lamp-failure` |
| 应答器/LEU | 20% 容量余量、默认回落、选择审计、逻辑字段/教学位流/仿真封装分层 | `test_leu_capacity_and_audit.py`、`test_logical_telegram.py` |
| 临时限速 | 45/80/120/160/200/250 km/h、80 m 重叠保护、制动距离/TCC/更新点 | `test_ctcs2_tsr_rules.py`、`temporary-speed` |
| 站间断链 | 已有方向/限速/报文保持；断链后锁闭，重连全量同步和复核 | `test_dual_station_end_to_end.py`、`test_interface_failure_recovery.py` |
| 列车演示 | 拓扑驱动 2D 线路、列车选择、逐段占用、应答器更新、选中列车复位重发车 | `test_train_projection.py`、`test_train_2d_view.py`、`test_dual_train_coordinator.py` |
| 日志告警 | A 上 B 下逐条事件，活动/恢复文字，最多 200 条，心跳不入业务日志 | `test_dual_log_page.py`、`test_tcc_controller.py` |

## 场景执行结果

1. 启动自检与双站握手：启动状态先显示 `INITIALIZING`，失败不会伪造健康；真实
   TCP 测试验证 HELLO/ACK、全量同步、健康状态和关闭资源回收。
2. A→B 运行：建立 `A_DEPART` 后，列车通过 `TrainProjectionMapper` 映射到
   `A_T1 → A_T2 → Q1…Q4 → B_T2 → B_T1`，区段先占后清，最后应答器字段更新。
3. 选中列车复位：下拉框保存稳定 `train_id`；`reset_train()` 成功后回到
   `WAITING`、递增 `lifecycle_version`，可再次派发；失败保留停车和保守占用。
4. 故障占用/分路不良：HU 和红灯防护保持，按后方出清顺序完成后才撤防，逐条
   告警可在 A/B 日志页查看。
5. 正常/异常改方：空闲且无冲突进路时完成事务；占用、方向不一致、通信异常或
   事务超时保持安全锁闭，不由 UI 绕过控制器。
6. 临时限速和 LEU：六档等级、重叠禁止、容量不足、LEU 断联默认回落及审计原因
   均有单元/集成证据；逻辑报文不冒充现场位流。
7. A/B 对称断链：通信页分别提供 A、B 链路故障入口，区间改方页提供逻辑对端
   断链入口；三者都只调用后端故障注入接口，恢复后自动重连和全量同步。

## UI 证据边界

三分辨率合成截图由 `scripts/capture_dual_dashboard.py` 生成，仅用于检查方案一
经典控制台风格、关键字段可见性、2D 列车和 A/B 日志布局；不能证明 TCP 握手。
真实通信、状态和资源证据以 pytest 集成为准。建议重新生成：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_dual_dashboard.py
```

## 结论

阶段 0～7 的代码、测试和交接账本已完成；阶段 8 的自动化规范矩阵、场景证据和
交付文档已纳入仓库。软件可用于 CTCS-2 课程答辩演示，不得用于真实铁路行车控制。
