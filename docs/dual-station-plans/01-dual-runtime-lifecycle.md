# 阶段 1：单进程双运行时与生命周期 Implementation Plan（实施方案）

> **给执行 Codex：** 必须使用 `superpowers:executing-plans`，严格测试先行；步骤均用复选框追踪。

**目标：** 在一个 Qt 进程中安全装配 A/B 两套独立运行时，A 真正监听后才启动 B，并提供确定性的反向关闭。

**架构：** 保留 `ApplicationRuntime` 单站职责，新增 `DualStationApplication` 只负责编排。A/B 仍走真实 TCP 协议，不共享控制器、仓储或状态对象。

**技术栈：** Python 3.12、PyQt5 QObject/QThread/信号槽、SQLite、pytest-qt。

**设计基线：** `docs/dual-station-plans/00-dual-station-design-spec.md`

## 全局约束与复审重点

- A=SERVER、B=CLIENT，地址/端口必须由配置交叉校验。
- 禁止固定延时启动 B；必须依赖 A `bind + listen` 后的 Qt 信号。
- 启动失败不能留下半开的数据库或线程。
- 关闭顺序固定为 B→A；控制器和数据库各关闭一次。
- 单站 `run.py --station A|B` 和现有 196 项测试必须保持兼容。

## 任务 1：把服务端就绪提升为 Qt 信号

**文件：** 修改 `app/network/network_worker.py`；测试 `tests/unit/test_network_thread.py`。

**接口：** `NetworkWorker.server_ready = pyqtSignal(str, int)`；runner 完成监听后发出，客户端永不发出。

- [ ] 先写测试：服务端 runner 监听随机端口后捕获一次 `(host, port)`；绑定失败时捕获零次。
- [ ] 运行定向测试并确认新测试因缺少 `server_ready` 失败。
- [ ] 让 `NetworkWorker` 用 `self.server_ready.emit` 作为 `PeerConnectionRunner.on_server_ready`，保留旧 callback 兼容仅到阶段完成。
- [ ] 运行：

```bash
.venv/bin/python -m pytest tests/unit/test_network_thread.py tests/integration/test_network_integration.py -q
```

## 任务 2：新增双运行时编排器

**文件：** 新建 `app/dual_application.py`；测试 `tests/unit/test_dual_application.py`。

**产出接口：**

```python
class DualStationApplication(QObject):
    lifecycle_changed = pyqtSignal(object)
    startup_failed = pyqtSignal(str)

    @classmethod
    def build(cls, *, config_dir: Path, data_root: Path) -> "DualStationApplication": ...
    def start(self) -> None: ...
    def stop(self, *, timeout_ms: int = 3000) -> bool: ...
```

- [ ] 用 fake runtime 写失败测试：`start()` 只先启动 A；收到 A ready 后只启动一次 B；A 报错时 B 不启动。
- [ ] 写关闭测试：B 先 stop、A 后 stop；B 停止失败时仍尝试 A，但返回 False 并记录两个结果；重复 stop 不重复关闭。
- [ ] 实现配置交叉校验：站点 ID、角色、peer ID、host/port 必须匹配，否则 `build` 抛出 `ConfigError` 且不创建数据库。
- [ ] 分别用 `data_root / "A"` 和 `data_root / "B"` 构建运行时，禁止共享 repository。
- [ ] 运行定向测试并通过。

## 任务 3：新增推荐入口

**文件：** 新建 `run_dual.py`；修改 `app/ui/qt_bootstrap.py` 仅复用现有 Qt 路径准备；测试 `tests/unit/test_command_line_tools.py`。

- [ ] 写 `--validate-only` 测试，预期输出 A/B 角色、共享端口和配置区段数量，不创建 QApplication/数据库。
- [ ] 实现参数 `--config`、`--data-root`、`--validate-only`，默认值均相对项目根目录。
- [ ] 非验证模式暂用最小占位窗口显示“A/B 运行时已装配”；阶段 3 才接正式主窗口。占位窗口必须有可测试文本，不添加虚假业务按钮。
- [ ] 关闭占位窗口调用 `DualStationApplication.stop()`；失败则拒绝退出并显示原因。

## 任务 4：回归、复审与提交

- [ ] 运行定向测试、全量 pytest、compileall、A/B/dual 配置校验和 `git diff --check`。
- [ ] 实际离屏运行 `run_dual.py`，确认 A/B 达到 HEALTHY，关闭后无存活线程和 socket。
- [ ] 更新 `docs/IMPLEMENTATION_STATUS.md`：接口、测试数、实测证据、下一阶段。
- [ ] 独立复审无 Critical/Important 后提交：

```bash
git add app/dual_application.py app/network/network_worker.py run_dual.py tests docs/IMPLEMENTATION_STATUS.md
git commit -m "feat: add single-process dual-station runtime"
git push origin codex/dual-station-dashboard
```

## 验收门

A 监听成功前 B 不启动；配置或监听失败安全退出；真实双站握手健康；关闭无泄漏；单站入口和全量回归通过。

## Codex 执行提示词

```text
执行双站同屏阶段 1。读设计基线、本文件、app/application.py 和 network_worker.py。测试先行新增 DualStationApplication；A 的 server_ready Qt 信号是启动 B 的唯一条件，禁止 sleep 猜测。A/B 控制器、SQLite、worker 必须独立，通信仍走真实 TCP。实现 run_dual.py 验证入口，测试失败启动、重复信号、反向关闭和单站兼容。全量回归、真实离屏握手、独立复审后提交推送并更新防中断文档。
```
