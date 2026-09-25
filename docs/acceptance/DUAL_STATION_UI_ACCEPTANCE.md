# 双站同屏 UI 视觉验收记录

验收日期：2026-09-26

分支：`codex/dual-station-dashboard`

设计基线：方案一“经典控制台风格”

## 证据边界

本目录图片由 `scripts/capture_dual_dashboard.py` 注入确定性的课程演示快照后
离屏生成，顶部均显示“合成状态 · 仅用于 UI 视觉验收”。它们只证明布局、
文字、颜色和控件可见性，不证明 TCP 已握手。真实握手、同步、重连和资源释放
由 `tests/integration/test_dual_station_end_to_end.py` 与
`tests/integration/test_dual_window_lifecycle.py` 独立证明。

重建命令：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_dual_dashboard.py
```

## 三分辨率截图

| 页面 | 1280×800 | 1440×900 | 1920×1080 |
|---|---|---|---|
| 双站总览 | [图片](dual-dashboard/synthetic_ui_overview_1280x800.png) | [图片](dual-dashboard/synthetic_ui_overview_1440x900.png) | [图片](dual-dashboard/synthetic_ui_overview_1920x1080.png) |
| 联合站场图 | [图片](dual-dashboard/synthetic_ui_corridor_1280x800.png) | [图片](dual-dashboard/synthetic_ui_corridor_1440x900.png) | [图片](dual-dashboard/synthetic_ui_corridor_1920x1080.png) |
| 区间改方 | [图片](dual-dashboard/synthetic_ui_direction_1280x800.png) | [图片](dual-dashboard/synthetic_ui_direction_1440x900.png) | [图片](dual-dashboard/synthetic_ui_direction_1920x1080.png) |
| 通信状态 | [图片](dual-dashboard/synthetic_ui_network_1280x800.png) | [图片](dual-dashboard/synthetic_ui_network_1440x900.png) | [图片](dual-dashboard/synthetic_ui_network_1920x1080.png) |
| 列车演示 | [图片](dual-dashboard/synthetic_ui_train_1280x800.png) | [图片](dual-dashboard/synthetic_ui_train_1440x900.png) | [图片](dual-dashboard/synthetic_ui_train_1920x1080.png) |

## 目视检查结果

- 三种分辨率均保留完整深蓝标题、全局安全状态和 12 项左侧导航；无按钮、
  表头或底部操作结果被窗口边界裁切。
- A/B 站身份、SERVER/CLIENT、连接状态、方向、状态版本、活动进路、边界码序、
  主信号、LEU、限速、告警和收发计数均有文字，不依赖颜色单独表达。
- 联合站场图的区段长度来自拓扑；下方表格补充区段归属、A/B 状态与码序、
  最终显示、一致性和判定依据，高分辨率空间用于有效信息。
- 区间改方页同时显示权威/投影角色、方向、通信、版本、事务阶段、锁闭状态和
  四项安全前置条件；故障演练按钮有明确措辞。
- 轨道状态使用深灰/红/棕/黄黑语义色，通信和告警同时给出文字；整体保持
  浅灰白背景、蓝色导航、白色细边框面板和紧凑表格。

结论：视觉验收通过。截图不替代真实运行证据。
