# 阶段 4：双站仿真协议与恢复说明

## 1. 定位与安全边界

本阶段协议用于两套独立 TCC 教学进程在 localhost 上交换仿真状态。它采用
长度帧、JSON 和 CRC32，便于观察、测试和答辩说明；CRC32 只能发现意外损坏，
不提供身份认证、加密或铁路安全通信能力。

## 2. TCP 帧格式

```text
+----------------------+-------------------------------+
| 4 字节大端正文长度 N | N 字节 UTF-8 规范 JSON 正文   |
+----------------------+-------------------------------+
```

- 正文长度范围为 `1..65536` 字节；零长度和超长声明立即关闭当前协议连接。
- `FrameDecoder` 保留未完成字节，可同时处理拆包、粘包和一次到达多帧。
- 连接重建时创建新的 decoder，不把旧连接残片带入新会话。

## 3. JSON 协议字段

每条消息固定包含：`magic`、`version`、`message_type`、`message_id`、
`sequence`、`station_id`、`peer_station_id`、`timestamp_ms`、
`state_version`、`payload`、`crc32`。正文使用 UTF-8、键名排序和紧凑分隔符
生成规范 JSON；CRC32 对不含 `crc32` 的其余字段计算。

接收端依次校验 UTF-8、JSON 对象、字段集合、CRC、协议版本和固定站点方向。
任一步失败都不会产生 `ProtocolMessage`，因此不会进入控制器。

## 4. 会话门禁

```text
TCP connected → HANDSHAKING → 收到 HELLO 且 ACK → HEALTHY
                                      │
                                      └→ 等待 STATE_SYNC 全量基线
                                             │
                                             └→ 允许增量业务消息
```

- 握手前只接受 `HELLO`、`ACK` 和 `ERROR`。
- 每次 TCP 重连都会清空对站 sequence、已见 message ID 和同步基线。
- message ID 重复或 sequence 不递增的消息被拒绝。
- 重连后，`STATE_SYNC` 到达前拒绝 `TRACK_BOUNDARY` 等增量消息。
- 本站使用单调时钟记录“实际收到消息”的时刻，不依赖对站系统时钟。

## 5. 心跳、降级与重连

正式 A/B 配置显式保存以下默认值：

| 参数 | 默认值 | 行为 |
|---|---:|---|
| `heartbeat_interval_ms` | 1000 | HEALTHY/DEGRADED 时发送心跳 |
| `degraded_after_ms` | 3500 | 达到阈值进入 DEGRADED |
| `disconnect_after_ms` | 6000 | 达到阈值断开并要求重新同步 |
| `reconnect_delays_ms` | 1000/2000/5000 | B 站依次退避，之后保持 5000 ms |

A 站作为 Server 持续监听，B 站作为 Client 负责退避重连。新连接完成握手后，
双方各发送一次由 `state_provider` 生成的全量状态；业务发送队列在收到对站
全量基线以前不会下发增量消息。

## 6. 线程与关闭规则

- 监听 socket、已连接 socket 的创建、收发和关闭全部位于 runner/worker 线程。
- GUI/控制器通过线程安全队列提交消息，通过 Qt signal 接收状态和消息。
- 发送队列上限为 256；新会话开始时丢弃旧会话/断线期增量，由全量同步
  重新建立唯一基线，防止过期状态跨重连补发。
- 停止操作只设置 `threading.Event`；worker 由短 socket 超时唤醒后自行关闭资源。
- `NetworkThreadController.stop()` 有明确超时，并等待 QThread 完成退出。

## 7. 自动化证据

- 属性测试随机覆盖协议载荷往返和任意拆/粘包组合。
- socketpair 测试覆盖坏 CRC、分片与跨线程误用。
- localhost 临时端口测试覆盖“客户端先启动—服务端上线—握手—心跳—双向
  全量同步—服务端重启—客户端重连—再次全量同步—线程退出—端口释放”。
