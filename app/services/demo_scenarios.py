"""供单窗口课程答辩复现的七类演示场景目录。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoScenario:
    """一个可定位、可执行、可验收并可复位的双站场景。"""

    scenario_id: str
    name: str
    target_page: str
    target_station: str
    preconditions: tuple[str, ...]
    control_object_names: tuple[str, ...]
    steps: tuple[str, ...]
    expected_results: tuple[str, ...]
    reset_steps: tuple[str, ...]


DELIVERY_SCENARIOS = (
    DemoScenario(
        "all-clear", "全空闲基线", "A站控制", "A站",
        ("用 run_dual.py 启动单窗口", "A/B 通信均为 HEALTHY", "Q1～Q4 空闲且方向为 A_TO_B"),
        ("establishRouteButton", "cancelRouteButton"),
        ("进入 A站控制/总览拓扑", "选择 A_DEPART 并单击建立进路"),
        ("联合锁闭保持解除", "区间形成配置码序且信号由码序唯一导出"),
        ("单击取消进路清除 A_DEPART",),
    ),
    DemoScenario(
        "block-occupied", "区间占用", "轨道电路", "A/B双站",
        ("A/B 通信健康且方向一致", "共享 Q 区段初始一致空闲"),
        ("applyTrackStateButton",),
        ("目标选择共享区间", "选择 Q3 和占用并应用轨道状态"),
        ("A/B 的 Q3 同时占用", "后方码序逐级降级且相关信号限制显示"),
        ("保持共享目标，将 Q3 改为空闲",),
    ),
    DemoScenario(
        "track-fault", "轨道故障", "轨道电路", "A/B双站",
        ("共享 Q2 初始一致空闲", "联合列车已复位或尚未创建"),
        ("applyTrackStateButton", "resetTrainButton"),
        ("目标选择共享区间", "将 Q2 设置为故障占用或分路不良"),
        ("Q2 输出保护码", "列车复位只清 TRAIN 来源，人工故障仍保留"),
        ("先将 Q2 人工输入改为空闲", "再到列车演示页复位列车"),
    ),
    DemoScenario(
        "red-lamp-failure", "红灯灯丝故障", "信号机控制", "A站",
        ("A/B 通信健康", "先使 SA 防护的 Q1 输出 HU，令 SA 应显示红灯"),
        ("applyTrackStateButton", "applySignalFailureButton"),
        ("在轨道页把共享 Q1 设为故障占用", "目标选择 A站和 SA", "勾选红灯灯丝故障并应用"),
        ("灯色显示 RED_LAMP_FAILURE", "产生严重告警且 HJ/UJ/LJ 均落下"),
        ("取消勾选并再次应用灯丝状态", "回到轨道页将共享 Q1 改为空闲"),
    ),
    DemoScenario(
        "temporary-speed", "临时限速", "临时限速", "A站",
        ("A站不存在同名未撤销命令", "起止里程与有效期合法"),
        ("prestoreTsrButton", "activateTsrButton", "cancelTsrButton"),
        ("目标选择 A站并填写 TSR-DEMO", "单击预存限速", "单击执行限速后查看应答器/LEU"),
        ("A站命令状态为 ACTIVE", "LEU 选择 CTCS-2 限速模板且 HEX 明确为仿真封装"),
        ("返回临时限速页并单击撤销限速",),
    ),
    DemoScenario(
        "direction-change-normal", "正常改方", "区间改方", "A/B双站",
        ("Q1～Q4 空闲", "两站无活动进路", "A/B 通信 HEALTHY 且方向一致"),
        ("requestDirectionButton",),
        ("选择 B站→A站", "单击由A站申请区间改方"),
        ("完成 PREPARE/APPROVE/COMMIT/ACK", "A/B 最终为 B_TO_A 并解除锁闭"),
        ("在相同安全条件下由 A 申请改回 A_TO_B",),
    ),
    DemoScenario(
        "direction-change-disconnect", "改方中断线", "通信状态", "A/B双站",
        ("A/B 初始通信 HEALTHY", "可控制测试环境中的 B 站网络生命周期"),
        ("requestDirectionDisconnectButton", "restoreBNetworkButton"),
        ("在区间改方页单击发起改方并立即中断B站", "观察锁闭后到通信状态页单击恢复B站网络"),
        ("双方相关作业安全锁闭且信号保持保护", "重连后按 A 权威方向和恢复证据同步"),
        ("等待两站恢复 HEALTHY 且方向一致", "条件不满足时保持锁闭并检查日志告警"),
    ),
)
