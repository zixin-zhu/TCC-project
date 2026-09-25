"""课程答辩使用的七类可复现场景目录。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoScenario:
    scenario_id: str
    name: str
    steps: tuple[str, ...]
    expected_results: tuple[str, ...]
    reset_steps: tuple[str, ...]


DELIVERY_SCENARIOS = (
    DemoScenario("all-clear", "全空闲基线", ("完成双站握手与全量同步", "确认所有区段空闲"),
                 ("方向锁闭解除", "区间形成配置码序且信号由码序唯一导出"), ("取消活动进路",)),
    DemoScenario("block-occupied", "区间占用", ("将运行前方区段设为占用",),
                 ("后方码序逐级降级", "相关信号保持或转为限制显示"), ("清除人工占用",)),
    DemoScenario("track-fault", "轨道故障", ("设置故障占用或分路不良",),
                 ("区段发送保护码", "列车来源出清后故障仍保留"), ("清除故障来源",)),
    DemoScenario("red-lamp-failure", "红灯灯丝故障", ("模拟受控信号机红灯灯丝故障",),
                 ("灯色显示 RED_LAMP_FAILURE", "产生严重告警且继电器均落下"), ("清除灯丝故障",)),
    DemoScenario("temporary-speed", "临时限速", ("预存合法限速命令", "执行限速"),
                 ("选择含 CTCS-2 限速包的逻辑报文", "HEX 明确标记为仿真封装"), ("撤销限速命令",)),
    DemoScenario("direction-change-normal", "正常改方", ("确认区间空闲且无进路", "由 A 申请 B_TO_A"),
                 ("完成 PREPARE/APPROVE/COMMIT/ACK", "A/B 最终方向一致并解除锁闭"), ("按相同步骤改回 A_TO_B",)),
    DemoScenario("direction-change-disconnect", "改方中断线", ("发起改方后断开站间连接",),
                 ("双方相关作业安全锁闭", "重连后以 A 权威方向和恢复证据恢复"), ("恢复网络并完成全量同步",)),
)
