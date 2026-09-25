# CTCS-2 车站列控中心 TCC 功能仿真

本项目是高铁列控课程设计软件，模拟两个车站 TCC 之间的 CTCS-2 教学场景：
轨道电路编码、信号点灯、应答器/LEU 逻辑报文、临时限速、区间改方、
双站 TCP 通信、告警与历史记录，以及配置驱动的列车占用演示。

> 重要声明：本软件只用于课程教学。JSON、HEX、CRC32 和“教学位流”均为
> `simulation_envelope`，不是现场 1023 位应答器报文，也不是经安全认证的
> 铁路通信或联锁设备，禁止用于真实铁路控制。

## 环境重建

推荐 macOS/Linux、Python 3.12 和 PyCharm。若使用 IDE，只需把项目解释器
设置为 `.venv/bin/python`。

```bash
cd /path/to/TCC-project
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

配置与 Qt 环境诊断：

```bash
.venv/bin/python run.py --station A --validate-only
.venv/bin/python run.py --station B --validate-only
.venv/bin/python scripts/diagnose_qt.py
```

项目会在创建 `QApplication` 前动态修复 PyQt5 位于中文路径时的平台插件
定位，不硬编码用户名或安装路径。

## 启动

分别启动单站：

```bash
.venv/bin/python run.py --station A
.venv/bin/python run.py --station B
```

推荐使用双站启动器。它先启动 A（Server），等本次 A 的网络线程完成
`bind + listen` 并发布一次性就绪凭据后再启动 B（Client），退出时统一回收
子进程：

```bash
.venv/bin/python scripts/launch_two_stations.py
```

两站 SQLite 分别写入 `data/A/tcc_a.db` 和 `data/B/tcc_b.db`。关闭窗口时会先
停止列车定时器和网络线程，再关闭数据库；网络线程未能按时停止时窗口拒绝退出。

## 测试

```bash
.venv/bin/python -m pytest -q
PYTHONPYCACHEPREFIX=/tmp/tcc-pycache \
  .venv/bin/python -m compileall -q app scripts run.py main.py run_new_ui.py
```

完整测试包含本机 `127.0.0.1` 随机端口上的双站握手、同步、断线重连和线程
关闭，因此受限沙箱需要允许本机回环 socket。

## 答辩演示

窗口提供总览/进路、轨道编码、信号、应答器与 LEU、临时限速、区间改方、
列车演示、网络、日志告警九页。推荐演示顺序及每一步的复位方法见
[`docs/DELIVERY_SCENARIOS.md`](docs/DELIVERY_SCENARIOS.md)。

列车页是教学动画：必须先建立当前方向的发车进路，再创建并发送列车。列车
占用只写 `TRAIN` 来源，复位或跨区出清不会清除人工占用、故障占用或分路不良。

## 关键安全降级规则

- A Server 是唯一区间方向权威；B 只保存投影。
- 启动、断线、快照过期、改方未确认或恢复未完成时，进路锁闭且信号保持红灯。
- A 的新权威方向必须先持久化，再在内存 APPLY 并发送 COMMIT。
- 数据库权威方向读取失败时阻止启动，不能用默认方向覆盖未知历史真值。
- 改方事务期间合并延迟普通状态同步，结束后补发一次最终全量状态。

## 目录

- `app/`：正式强类型领域、服务、网络、持久化和 PyQt UI。
- `configs/`：A/B、拓扑、码序、应答器组和逻辑报文配置。
- `scripts/`：Qt 诊断与双站启动工具。
- `tests/`：单元、Qt 和本机双站集成测试。
- `legacy/`：确认不再被正式入口引用的初始版本代码，仅供对照。
- `docs/IMPLEMENTATION_STATUS.md`：防中断实施状态与恢复入口。
