from datetime import datetime


class BaliseService:
    """
    有源应答器报文编制服务。

    根据当前TCC运行状态动态生成
    应答器仿真报文。
    """

    def __init__(self, simulation_service):
        self.simulation = simulation_service

    def get_active_balise(self):
        """
        根据当前运行方向确定入口应答器。
        """

        direction = self.simulation.get_direction()

        if direction == "A_TO_B":
            return {
                "id": "B001",
                "location": "A站区间入口"
            }

        return {
            "id": "B002",
            "location": "B站区间入口"
        }

    def generate_message(self):
        """
        根据当前区间状态生成应答器报文。
        """

        direction = self.simulation.get_direction()

        balise = self.get_active_balise()

        tracks = (
            self.simulation.get_all_track_status()
        )

        # 判断区间是否全部空闲
        all_clear = all(
            track["status"] == "空闲"
            for track in tracks
        )

        # 根据运行方向确定入口闭塞分区
        if direction == "A_TO_B":
            entrance_track = tracks[0]
        else:
            entrance_track = tracks[-1]

        entrance_code = entrance_track[
            "track_code"
        ]

        # 运行方向文字
        if direction == "A_TO_B":
            direction_text = "A站 → B站"
        else:
            direction_text = "B站 → A站"

        # 区间状态
        if all_clear:
            section_status = "区间空闲"
        else:
            section_status = "区间占用"

        # 结构化报文
        message = {
            "balise_id": balise["id"],
            "location": balise["location"],
            "direction": direction_text,
            "section_status": section_status,
            "entrance_track_code": entrance_code,
            "train_position": (
                self.simulation.train_position
                if self.simulation.train_position
                else "区间外"
            ),
            "generate_time": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        return message

    def encode_message(self, message):
        """
        将结构化报文编码为仿真传输字符串。
        """

        raw_message = (
            f"BALISE={message['balise_id']}|"
            f"LOC={message['location']}|"
            f"DIR={message['direction']}|"
            f"SECTION={message['section_status']}|"
            f"CODE={message['entrance_track_code']}|"
            f"TRAIN={message['train_position']}|"
            f"TIME={message['generate_time']}"
        )

        return raw_message

    def build_balise_packet(self):
        """
        生成完整的有源应答器报文包。
        """

        message = self.generate_message()

        raw_message = self.encode_message(
            message
        )

        return {
            "message": message,
            "raw": raw_message
        }