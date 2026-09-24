class Balise:

    def __init__(
        self,
        balise_id,
        balise_type,
        location,
        track_code=None,
        line_speed=120.0,
        gradient=0.0,
        next_track=None,
        next_speed=None
    ):

        self.balise_id = balise_id

        # 兼容旧代码
        self.code = balise_id

        self.balise_type = balise_type
        self.location = location
        self.track_code = track_code

        self.line_speed = float(
            line_speed
        )

        self.gradient = float(
            gradient
        )

        # 下一闭塞分区
        self.next_track = next_track

        # 下一闭塞分区线路限速
        self.next_speed = next_speed

    def get_message(self):
        return {
            "balise_id": self.balise_id,
            "type": self.balise_type,
            "location": self.location,
            "track_code": self.track_code,
            "line_speed": self.line_speed,
            "gradient": self.gradient,
            "next_track": self.next_track,
            "next_speed": self.next_speed
        }