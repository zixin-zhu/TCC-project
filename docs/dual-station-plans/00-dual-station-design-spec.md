# TCC 单界面双站联合仿真设计基线

## 1. 文档目的

本文定义后续阶段方案共同遵守的产品目标、架构边界、界面信息架构、状态来源、
生命周期和验收标准。本文不是单体实施方案；具体实现必须拆分为
`00-workspace-git-recovery.md` 至 `05-integration-delivery.md` 六个阶段文件，
每阶段独立测试、复审、提交和推送。

## 2. 已确认目标

将当前两个独立 `TccMainWindow` 改造成一个清晰的双站联合仿真窗口：

- 一个 `QApplication`、一个顶层主窗口，同时运行 A、B 两套真实 TCC。
- A、B 各自保持独立控制器、运行状态、网络会话、告警服务和 SQLite 数据库。
- 两站继续通过现有 TCP/IP、HELLO/ACK、状态同步和改方事务通信，禁止为了界面
  方便而直接复制对站业务状态、绕过协议或取消安全门禁。
- 首页同时看见两站身份、通信、方向、锁闭、进路、信号、轨道码序、列车、
  应答器/LEU、临时限速、告警和网络计数等关键数据。
- 复杂操作放在详情页，首页不堆放大表格和长报文。
- 视觉严格采用用户参考图左上角“方案一：经典控制台风格”：浅灰白工作区、
  深蓝标题栏、蓝色选中导航、细边框分组框、紧凑状态表和工业监控语义色。
- 继续维持 CTCS-2 教学定位和现有仿真边界，不宣称现场安全认证能力。

## 3. 当前基线与前置故障

正式实现位于：

```text
/Users/zhu/Desktop/TCC-project/.worktrees/ctcs2-rebuild
```

桌面目录由“列控课设”改名为 `TCC-project` 后，工作树 `.git` 文件仍指向：

```text
/Users/zhu/Desktop/列控课设/pythonProjectTest/.git/worktrees/ctcs2-rebuild
```

因此当前 Git 命令无法识别正式工作树。必须在阶段 0 先修复以下两侧元数据：

1. 正式工作树 `.git` 中的 `gitdir` 改为新绝对路径。
2. 主仓库 `.git/worktrees/ctcs2-rebuild/gitdir` 改为新工作树 `.git` 路径。
3. 验证 HEAD 仍为 `codex/ctcs2-rebuild`，并与远端提交 `5a8e06e` 对应。
4. 禁止重新初始化仓库、删除 `.git`、复制覆盖索引或把旧 `pythonProjectTest`
   当成正式代码重新开发。

修复前只允许读取和撰写方案，不允许提交实现。

## 4. 方案选择

### 4.1 采用方案

采用“单进程双运行时 + 总览驾驶舱 + 分站详情组件”：

- `DualStationApplication` 负责构建和管理两个 `ApplicationRuntime`。
- `DualStationMainWindow` 是唯一顶层窗口。
- `DualStationSnapshotAggregator` 只读组合 A/B 快照，生成总览模型。
- `StationDetailWidget` 复用现有单站九页功能，不拥有网络线程和数据库生命周期。
- `CorridorOverviewWidget` 绘制统一线路、方向、信号、区段、码序、应答器、限速
  和列车位置。

### 4.2 不采用方案

- 不把两个完整九页窗口直接左右并排：在 1440×900 下信息过密且操作区域过窄。
- 不增加第三个总控进程：会引入新的进程间协议和第三份状态，超过课程项目需要。
- 不让 A/B 共用同一个 `TccController` 或 SQLite 连接：会破坏两站独立性和线程边界。
- 不删除单站启动入口：`run.py --station A|B` 继续用于诊断和兼容验证。

## 5. 总体架构

```text
QApplication
└── DualStationApplication
    ├── ApplicationRuntime[A]
    │   ├── TccController[A]
    │   ├── NetworkWorker[A] / QThread
    │   └── SQLiteRepository[data/A/tcc_a.db]
    ├── ApplicationRuntime[B]
    │   ├── TccController[B]
    │   ├── NetworkWorker[B] / QThread
    │   └── SQLiteRepository[data/B/tcc_b.db]
    ├── DualStationSnapshotAggregator
    ├── DualTrainCoordinator
    └── DualStationMainWindow
        ├── GlobalStatusBar
        ├── StationSummaryCard[A]
        ├── StationSummaryCard[B]
        ├── CorridorOverviewWidget
        └── DetailTabs
            ├── 双站总览
            ├── A站控制
            ├── B站控制
            ├── 应答器/LEU
            ├── 临时限速
            ├── 区间改方/网络
            ├── 列车演示
            └── 日志告警
```

`DualStationApplication` 只负责编排，不实现编码、点灯、报文、改方或进路规则。
所有业务写操作仍调用目标站 `TccController`。

## 6. 启动与关闭时序

### 6.1 启动

1. 加载并交叉校验 A/B 配置，确认角色为 A=SERVER、B=CLIENT，地址和端口一致。
2. 分别创建 `data/A/tcc_a.db` 与 `data/B/tcc_b.db` 的仓储和控制器。
3. 创建两个网络 worker，但先只启动 A。
4. A 的 worker 在自身线程完成 `bind + listen` 后发出
   `server_ready(str host, int port)` Qt 信号。
5. GUI 主线程收到信号后启动 B；不得使用固定毫秒延时推测 A 已就绪。
6. 两站完成 HELLO/ACK、全量同步和方向恢复后，总览状态从“启动锁闭”转为
   “通信健康/允许作业”。
7. 若 A 监听失败，B 不启动，窗口保留并显示严重告警和可执行原因。

### 6.2 关闭

1. 禁用新的界面命令并停止联合列车定时器。
2. 先停止 B 客户端网络线程，再停止 A 服务端网络线程。
3. 两个线程均在超时内结束后，各自只关闭一次控制器和数据库。
4. 任一线程未停止时拒绝窗口关闭、恢复必要定时器并显示具体站点和原因。
5. 禁止重复调用 `controller.close()`；生命周期所有权统一归
   `DualStationApplication.stop()`。

## 7. 快照聚合模型

新增不可变 `DualStationSnapshot`，至少包含：

```python
@dataclass(frozen=True)
class SectionConsistency:
    section_id: str
    station_a_state: TrackState
    station_b_state: TrackState
    consistent: bool
    display_state: TrackState | None
    reason: str


@dataclass(frozen=True)
class DualStationSnapshot:
    station_a: TccSnapshot
    station_b: TccSnapshot
    authoritative_direction: RunningDirection
    direction_consistent: bool
    communication_healthy: bool
    operation_locked: bool
    sections: tuple[SectionConsistency, ...]
    active_alarm_count: int
    critical_alarm_count: int
```

聚合器遵守以下规则：

- A 的方向是唯一权威方向；B 的方向仅用于一致性校验。
- A/B 任一通信非 `HEALTHY`、任一方向锁闭或方向不一致时，全局显示安全锁闭。
- 站内区段 `A_T*` 以 A 快照为显示来源，`B_T*` 以 B 快照为显示来源。
- 共享闭塞分区 Q1～Q4 同时保留两站观察值；一致时显示状态，不一致时显示
  “同步中/不一致”，不能静默采用其中一个值。
- 总告警数是两站活动告警之和；相同代码但不同站点不能合并丢失来源。
- 聚合器不得修改控制器、不得自动清故障、不得生成业务版本号。

## 8. 界面信息架构

### 8.1 顶部标题栏与全局状态条

标题栏左侧固定显示“CTCS-2 车站列控中心（TCC）双站联合仿真系统”，右侧显示
A/B 连接摘要和运行状态。标题栏下不照搬无实现的“系统设置/帮助”等菜单；只保留
真实可用的导航和操作。全局状态区始终显示：

| 字段 | 来源 | 显示规则 |
|---|---|---|
| 系统运行状态 | 双运行时生命周期 | 启动中/运行/降级/关闭失败 |
| 站间通信 | A/B `connection_state` | 双方 HEALTHY 才显示绿色 |
| 当前方向 | A 权威方向 | A→B 或 B→A，附方向箭头 |
| 作业状态 | 聚合锁闭值 | 允许/安全锁闭 |
| 活动告警 | 两站告警汇总 | 总数和严重告警数 |
| 仿真状态 | 联合列车协调器 | 停止/运行/暂停及倍率 |

### 8.2 左侧功能导航

采用参考图方案一的浅色竖向导航，顺序固定为：

1. 双站总览；
2. 联合站场图；
3. A站控制；
4. B站控制；
5. 轨道电路；
6. 信号机控制；
7. 应答器/LEU；
8. 临时限速；
9. 区间改方；
10. 通信状态；
11. 列车演示；
12. 日志告警。

导航使用 `QListWidget` 或一组互斥 `QToolButton` 驱动 `QStackedWidget`。每个入口
必须有实际页面；禁止出现空按钮、未实现弹窗或仅为装饰的菜单项。

### 8.3 A/B 站摘要卡

两张卡片左右对称，每张卡必须显示：

- 站名、站点 ID、SERVER/CLIENT 角色。
- 通信状态、状态版本、发送数、接收数。
- 当前方向投影和方向作业锁闭状态。
- 活动进路；无进路时明确显示“无”。
- 本站边界区段状态和对应码序。
- 本站主信号机灯色及 HJ/UJ/LJ 继电器摘要。
- LEU 端口、报文模板、正常/默认模式。
- 临时限速数量、活动告警数量和最高告警等级。
- “进入 A站控制”或“进入 B站控制”按钮，只切换详情页，不直接改变业务状态。

颜色不是唯一信息载体；绿色、黄色、红色、紫色状态旁必须有中文文字。

### 8.4 统一线路图

线路按配置顺序绘制：

```text
A站 / A_T1 / A_T2 / Q1 / Q2 / Q3 / Q4 / B_T2 / B_T1 / B站
```

每个区段同时显示：ID、中文名称、有效状态、轨道码、长度。区段上方绘制信号机，
下方绘制应答器组；活动临时限速以半透明黄色范围条显示；列车以带 ID 的矩形图元
显示；当前权威方向用蓝色箭头显示。状态颜色固定为：

- 空闲：深灰。
- 列车占用：红色。
- 故障占用：紫色。
- 分路不良：橙色。
- 两站不一致：黄黑斜纹并显示“不一致”。
- 锁闭：线路图顶部显示红色“安全锁闭”横条。

绘图使用 `QPainter` 和布局尺寸动态计算，不使用截图中的固定像素坐标。

### 8.5 快捷操作区

参考方案一的“快捷操作”只放当前软件已有且安全条件明确的动作：

- 建立/取消目标站进路；
- 设置/清除轨道人工状态或故障状态；
- 设置/恢复信号机红灯灯丝故障；
- 预存、执行、撤销临时限速；
- 由 A 站申请区间改方；
- 创建、发送、运行、暂停、复位教学列车。

按钮文字必须包含动作和对象；危险或改变状态的操作使用蓝色主按钮、黄色警示或
红色故障按钮，但颜色不代替文字。通信启动由运行时自动完成，不设置“连接服务器”
或“开启服务器”按钮，以免制造与真实生命周期不一致的假功能。

### 8.6 详情页

- `双站总览`：摘要卡、统一线路图、最近 10 条关键事件和严重告警。
- `A站控制`、`B站控制`：嵌入可复用单站详情组件，保留轨道、进路、信号操作。
- `应答器/LEU`：左右对照两站逻辑报文；教学位流和仿真封装通过子标签展开。
- `临时限速`：站点选择器明确目标控制器，列表同时展示 A/B 状态。
- `区间改方/网络`：显示事务阶段、A 权威方向、B 投影、通信计数和连接状态；
  只有 A 侧按钮可发起改方。
- `列车演示`：统一创建、发送、运行、暂停、复位，显示列车区段、位置、速度、
  目标速度、前方距离、最后应答器和安全状态。
- `日志告警`：站点筛选、级别筛选；每行保留站点来源。

## 9. 单站界面组件化

现有 `TccMainWindow` 同时承担顶层窗口、九页组件和生命周期，必须按职责拆分：

- `StationDetailWidget(QWidget)`：接收一个 `TccController`，创建单站业务页面，
  只发命令和刷新快照。
- `StationSummaryCard(QGroupBox)`：只显示本站摘要并发出导航信号。
- `TccMainWindow(QMainWindow)`：保留为单站兼容壳，内部嵌入
  `StationDetailWidget`，继续支持 `run.py --station A|B`。
- `DualStationMainWindow(QMainWindow)`：组合两个详情组件和双站专用页面。
- QSS 移至 `app/ui/styles.py` 或资源文件，禁止在多个窗口复制长字符串。

组件不得直接访问另一个站的控制器，不得在 UI 中重写领域判断。

## 10. 联合列车演示

新增 `SharedTrackInputAdapter` 和 `DualTrainCoordinator`，而不是让两个
`TrainDemoService` 各自生成同名列车：

- 协调器持有一份列车演示状态和一个 500 ms `QTimer`。
- 站内区段只写所属站控制器；共享 Q1～Q4 模拟同一物理轨道检测输入，由
  `SharedTrackInputAdapter` 把同一个 TRAIN 输入分别提交给 A、B 控制器。
- 该适配器模拟外部轨道检测设备向两站提供同源输入，不读取一站状态再复制给另一站；
  两站仍通过现有网络同步彼此报告的状态并进行一致性校验。
- 所有占用仍只调用各站控制器
  `set_track_state(section_id, TrackInputSource.TRAIN, state)`；转换时先占用下一段，
  两次提交均成功后再出清上一段，任一失败则停车并保持较保守的占用状态。
- 改方锁闭、通信降级、前方占用或方向不一致时列车暂停并显示原因。
- 复位只清除 TRAIN 来源，不清除人工、故障和分路不良来源。
- 教学动画不声称实现车载 ATP、真实测速定位或制动曲线。

## 11. 操作权限与安全降级

- 启动未完成：所有进路、改方和列车发送按钮禁用。
- 通信 `DEGRADED`/`DISCONNECTED`：保留可安全执行的本地故障注入和查看功能，
  禁止建立依赖对站状态的进路、改方和跨站列车运行。
- 改方事务期间：两站相关作业锁闭、信号保持红灯、列车暂停。
- A/B 方向不一致：显示严重告警并锁闭，不允许 UI 自动纠正 B。
- 数据库恢复失败：对应站运行时不启动；不得以默认方向覆盖未知权威历史。
- 用户操作必须显示成功/拒绝、原因、目标站和状态版本。

## 12. 经典控制台视觉与响应式规范

- 最低支持 1280×800；推荐 1440×900 和 1920×1080。
- 主背景使用 `#eef2f5`，内容面板使用 `#ffffff`，标题栏使用 `#07558f` 至
  `#0b6cad` 的蓝色，边框使用 `#b8c7d3`，正文使用 `#1f2d38`。
- 导航选中态使用 `#1976d2` 蓝底白字，普通态为浅灰底深色字；按钮保持小圆角、
  细边框和紧凑高度，不采用深色卡片、霓虹渐变或大面积高饱和背景。
- 分组框标题采用浅蓝灰表头，表格为白底、细网格、紧凑行高，整体视觉与参考图
  方案一一致，但站场对象数量和按钮名称必须来自本项目配置与真实功能。
- 使用 `QVBoxLayout`、`QHBoxLayout`、`QGridLayout`、`QSplitter` 和尺寸策略，
  禁止 `setGeometry` 固定布局。
- 小于 1450 px 时摘要卡仍左右排列，但字段改为紧凑两列；详情表格允许滚动。
- 表格列使用 `QHeaderView.Stretch` 与按内容混合策略，关键 ID 列不被截断。
- 颜色统一通过动态属性 `severity`、`connectionState`、`trackState` 驱动 QSS。
- 字体使用系统默认字体和点数，不硬编码只在某个平台存在的字体。
- 所有图标或色块均配文字或工具提示，保证黑白截图仍可理解。
- 不照抄参考图中四股道、S1～S8、B1/B2 等示意对象；当前配置只有 A_T1、A_T2、
  Q1～Q4、B_T2、B_T1 和 SA/S1/S2/S3/SB，界面必须配置驱动，避免虚构设备。

## 13. 兼容入口

- 新增 `run_dual.py` 作为推荐入口：

  ```bash
  .venv/bin/python run_dual.py
  ```

- 保留：

  ```bash
  .venv/bin/python run.py --station A
  .venv/bin/python run.py --station B
  ```

- 原 `scripts/launch_two_stations.py` 保留为多进程诊断工具，但 README 将
  `run_dual.py` 标记为课程演示推荐方式。

## 14. 测试与验收总原则

每阶段严格测试先行，至少覆盖：

1. A 监听完成前 B 不启动；A 失败时 B 永不启动。
2. 两站数据库文件和连接完全隔离，关闭各执行一次。
3. 两站快照乱序到达时，聚合器不产生混合版本或错误解锁。
4. Q1～Q4 状态不一致时，总览明确报警且全局锁闭。
5. 单站兼容入口和原 196 项测试不得回归。
6. 所有首页关键字段都由快照驱动，按钮没有空实现。
7. 双站窗口关闭时线程、定时器、socket 和 SQLite 均无泄漏。
8. 1280×800 与 1920×1080 下无关键字段遮挡。
9. 七类既有答辩场景在单窗口中全部可完成并复位。
10. 截图证据明确区分合成 UI 状态和真实双站握手证据。

## 15. 阶段拆分

后续必须生成以下独立方案：

| 阶段 | 文件 | 独立交付物 |
|---|---|---|
| 0 | `00-workspace-git-recovery.md` | 修复重命名后的 Git 工作树并建立新分支 |
| 1 | `01-dual-runtime-lifecycle.md` | 单进程 A/B 运行时、顺序启动与可靠关闭 |
| 2 | `02-station-ui-refactor.md` | 可嵌入单站组件与兼容单站窗口 |
| 3 | `03-dashboard-corridor.md` | 双站摘要卡、聚合模型和统一线路图 |
| 4 | `04-dual-operations-train.md` | 双站操作页、改方/网络和联合列车演示 |
| 5 | `05-integration-delivery.md` | 全量场景、视觉测试、文档、截图和最终交付 |

每个阶段文件必须包含：背景依赖、明确范围、接口定义、逐步 TDD 任务、异常路径、
测试命令、验收门、Git 提交/推送要求、防中断文档更新内容和一段可复制的 Codex
执行提示词。阶段 N 只有在测试、独立复审和推送完成后，才能开始阶段 N+1。

## 16. 非目标

- 不实现真实铁路联锁接口、硬件冗余或安全认证通信。
- 不生成或宣称真实应答器 1023 位报文。
- 不实现车载 ATP、精确制动模型或工程级列车追踪。
- 不新增远程 Web 服务、浏览器前端或第三方数据库。
- 不在本次 UI 改造中改变既有 CTCS-2 编码、点灯、LEU 或改方业务规则。

## 17. 完成定义

当且仅当六个阶段分别完成、推送且满足以下条件，双站同屏改造才算完成：

- `run_dual.py` 一次启动一个窗口并建立真实 A/B TCP 会话。
- 首页无需切页即可读出第 8 节规定的全部关键状态。
- 单站兼容入口、全套自动测试和七类答辩场景全部通过。
- 无 Critical/Important 复审问题，无线程、socket、数据库泄漏。
- 防中断文档记录当前阶段、提交号、测试数量、已知限制和下一步。
