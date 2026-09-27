# CTCS-2 规范需求追踪表

本表是执行方案的机器可检查索引。原始规范为图像型 PDF，页码按 PDF 扫描页记录；本项目只实现可复现的教学仿真，不宣称达到现场安全设备的 SIL、RAMS 或物理接口指标。

| ID | 规范/教学要求 | 软件落地点 | 验收证据 |
|---|---|---|---|
| SPEC-01 | 车站/中继 TCC 独立编号和控制范围 | `configs/`、`app/core/models.py` | 配置唯一性测试 |
| SPEC-02 | CBI、CTC、LEU、轨道电路、相邻 TCC、监测接口 | `app/services/interface_status_service.py` | 接口状态和断链测试 |
| SPEC-03 | 报文调用、轨道编码、信号点灯、进路和闭塞 | `app/domain/`、`app/services/tcc_controller.py` | 核心功能矩阵 |
| SPEC-04 | 双向运行和安全改方 | `app/domain/direction_change.py` | 正反向事务测试 |
| SPEC-05 | 正常占用、故障占用、分路不良和占用出清顺序 | `app/domain/track_circuit.py` | 故障恢复顺序测试 |
| SPEC-06 | 站内/区间码序、方向切换和故障离线 | `app/domain/track_circuit.py` | 码序与离线测试 |
| SPEC-07 | LEU 报文选择、20% 存储余量和错误防护 | `app/domain/leu.py`、`balise_telegram.py` | LEU 余量/默认报文测试 |
| SPEC-08 | 进站、出站、到发线、中继应答器组 | `configs/balise_groups.json` | 正反向组选择测试 |
| SPEC-09 | 45/80/120/160/200/250 km/h 临时限速 | `app/domain/temporary_speed.py` | 六等级和重叠测试 |
| SPEC-10 | 统一接口协议和通信状态监视 | `app/network/`、接口状态服务 | 协议和恢复测试 |
| SPEC-11 | 2×2 取 2、诊断、监测和报警的教学模型 | `app/services/interface_status_service.py` | 诊断降级测试 |
| SPEC-12 | 区间信号、灯丝继电器、红灯防护 | `app/domain/signal_control.py` | HJ/UJ/LJ 和红灯测试 |
| SPEC-13 | CTC/TCC 断链保持既有限速、方向和安全报文 | `app/services/peer_sync_service.py` | 断链保持测试 |
| SPEC-14 | 启动自检和按序建立外部通信 | `app/dual_application.py` | 启动状态机测试 |
| SPEC-15 | 运行状态、故障、日志和告警可监视查询 | `app/ui/dual_log_page.py`、SQLite | A/B 日志逐条回读 |
| SPEC-16 | 列车跨区段运行和设备联动可视化 | `app/services/train_projection.py`、`app/ui/train_scene.py` | 2D 场景验收 |

## 规范边界

- Python/Qt 只模拟业务规则和可视化，不声称实现现场 2×2 取 2、SIL4、MTBF、EMC、双路电源或安全通信认证。
- JSON、HEX、CRC32 只能称为 `simulation_envelope`，不能称为现场应答器物理报文。
- 大号码道岔、CTCS-0 接口和中继站用最小教学场景表示，界面和报告必须标注“仿真简化”。
