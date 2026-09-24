# 阶段 5：区间改方事务与失败恢复

## 1. 事务目标

改方不再沿用旧代码“收到申请即切向”的做法。经阶段 5 架构复核，采用
**A 站唯一方向权威、B 站只保存权威投影**的模型，避免两个站点形成可独立
提交、相互冲突的方向真值：

```text
A 站 PREPARE → B 站 APPROVE（只预留，双方锁闭方向作业）
A 站复核并提交唯一权威方向 → COMMIT
B 站复核、应用权威方向投影 → ACK
A 站收到 ACK 后解除本站锁闭，并发送 DIRECTION_CONFIRM
B 站复核确认及当前安全条件后解除投影锁闭
```

状态机本身不调用 Qt、socket 或 UI。它只读取不可变 `DirectionGuard`，产出
`SEND`、`APPLY`、`RELEASE`、`LOG` Action，由控制器执行。

## 2. 双方必须同时满足的守卫

- 网络状态必须为 `HEALTHY`，仅 TCP connected 不够。
- 对站快照必须新鲜。
- `required_section_ids` 必须全部出现在快照中，且每一区段均为 `CLEAR`。
- 不得存在 `OCCUPIED`、`FAULT_OCCUPIED` 或 `SHUNT_BAD`。
- 不得存在活动进路、故障锁闭或其他活动改方事务。
- 事务记录的申请方版本、预期响应方版本与双方当前快照必须一致。
- COMMIT 到达响应方时重新执行全部守卫，不复用 APPROVE 时的旧结论。

## 3. 结构化拒绝矩阵

| 拒绝码 | 含义 | 是否切向 |
|---|---|---|
| `COMMUNICATION_UNHEALTHY` | 通信并非 HEALTHY | 否 |
| `PEER_SNAPSHOT_STALE` | 对站快照过期 | 否 |
| `SECTION_UNSAFE` | 区段缺失、占用、故障占用或分路不良 | 否 |
| `ROUTE_CONFLICT` | 存在活动进路 | 否 |
| `ACTIVE_TRANSACTION` | 已有改方事务/预留 | 否 |
| `WRONG_TRANSACTION` | UUID 或事务归属错误 | 否 |
| `VERSION_MISMATCH` | 本地/对站状态版本不一致 | 否 |
| `DIRECTION_MISMATCH` | 原方向或目标方向不一致 | 否 |
| `OUT_OF_ORDER` | 报文阶段乱序 | 否 |
| `NOT_AUTHORITY` | 非 A 站尝试发起改方 | 否 |
| `RECOVERY_PENDING` | 方向尚在安全锁闭/恢复中 | 否 |
| `TIMEOUT` / `DISCONNECTED` | 等待超时或连接中断 | 保持当前方向并锁闭到安全重同步完成 |

`REJECT` 是终止消息：无法关联活动事务时只记录，不再回发另一个 REJECT，
避免两个站点形成拒绝报文循环。

## 4. 幂等与协议约束

- `transaction_id` 必须是 UUID。
- 幂等缓存以完整不可变领域消息为键，而非只看“类型 + UUID”；同 UUID
  但方向、版本或期限变化会重新校验并拒绝。
- 缓存最多保存 256 个结果，超出后淘汰最旧项。
- PREPARE/COMMIT 必须由申请站发送；APPROVE/ACK 必须由响应站发送；
  REJECT 可由任一事务参与站发送。
- 五类消息均通过阶段 4 的规范 JSON、站点方向、状态版本和 CRC32 往返测试。

## 5. 单一权威与失败恢复模型

A 站是唯一能发起并提交方向的站点。B 站收到 COMMIT 后只更新 A 站权威方向
的本地投影。改方开始到投影确认期间，`LOCK` Action 会令双方禁止建立新进路，
信号计算强制保持红灯；`sendall` 成功只用于日志，绝不当作对端已处理的证明。

通信正常时收到明确安全拒绝，可以释放预留并保持原方向；任何超时或断线都
进入 `FAULT_LOCKED`。若在 A 提交之后 ACK 或 DIRECTION_CONFIRM 丢失，任何
一方都不得回滚权威方向。双方进入或保持
`FAULT_LOCKED`，重连后通过阶段 4 全量同步取得 A 站方向，再重新检查通信、
快照、区间空闲和进路条件，条件全部满足后才执行 `UNLOCK`。B 站始终无权以
本地状态覆盖 A 站方向。

这是课程仿真的受控恢复模型，不等同于铁路安全通信或在任意网络分区下的
分布式共识。阶段 6 负责把恢复记录持久化；真实安全系统还需要专用安全传输、
冗余控制和经安全认证的恢复协议。

## 6. 自动化验收证据

- 正反两个方向均完成 PREPARE→APPROVE→COMMIT→ACK。
- APPROVE 后双方方向保持不变。
- COMMIT 前出现新占用时响应方拒绝并释放预留。
- A 站独占发起权，B 站不能创建竞争方向事务。
- 提交后的 ACK/确认丢失不会回滚权威真值，而是锁闭到安全重同步完成。
- 锁闭期间进路建立被拒绝，所有相关信号保持红灯。
- WAIT/COMMIT 超时、断线、重复包、错 UUID、版本回退、篡改重复包、
  同时申请和 REJECT 循环均有自动化测试。
