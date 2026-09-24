# 阶段 3 应答器逻辑报文黄金场景

> 下列结果是课程逻辑报文和 `simulation_envelope`，不是现场可下装的 1023 位应答器报文。

| 场景 | LEU 条件 | 结果模板 | 模式 | 告警 |
|---|---|---|---|---|
| 正常发车进路 | 已连接，输入新鲜，匹配进路 | `TG_A_ROUTE` | `SELECTED` | 无 |
| 临时限速 | 已连接，输入新鲜，TSR 已执行 | `TG_A_TSR`，含 CTCS-2 包 | `SELECTED` | 无 |
| 无匹配条件 | 已连接，输入新鲜，无选择模板 | `TG_A_DEFAULT` | `DEFAULT` | WARNING |
| LEU 输入断联 | 未连接 | `TG_A_DEFAULT` | `FAULT_DEFAULT` | CRITICAL |
| 输入过期 | 超过 3500 ms | `TG_A_DEFAULT` | `FAULT_DEFAULT` | CRITICAL |
| 所选报文校验失败 | 字段越界或限速起终点反转 | `TG_A_DEFAULT` | `FAULT_DEFAULT` | CRITICAL |

可追溯字段包括：应答器组、应答器单元、方向、模板、状态版本、信息包清单、选择模式与原因。CRC32 只校验本软件规范 JSON 是否变化，不代表铁路安全完整性机制。
