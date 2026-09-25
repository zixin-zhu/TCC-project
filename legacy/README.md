# 初始版本归档

本目录保存 `d62e396` 初始版本中已经被正式 `app/` 架构替换的代码，仅供课程
设计过程对照，不作为可运行入口，也不再接受功能修补。

归档前已使用 `rg` 扫描正式 `app/`、`tests/`、`run.py`、兼容入口和 `scripts/`，
确认它们不导入顶层旧 `models`、`services`、`network` 或 `ui` 包。历史文件仍
保留原来的绝对导入写法，因此不要从 `legacy/` 直接启动。

正式入口：

```bash
python run.py --station A
python run.py --station B
python scripts/launch_two_stations.py
```

如需查看初始实现，可直接阅读本目录或通过 Git 基线提交 `d62e396` 对照。
