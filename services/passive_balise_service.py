from models.balise import Balise


class PassiveBaliseService:

    def __init__(self):

        self.balises = {}

        self.create_default_balises()

    def create_default_balises(self):

        data = [
            # 应答器 当前分区 当前限速 坡度  下一分区 下一限速

            ("B01", "G01", 120, 0.0, "G02", 120),
            ("B02", "G02", 120, 0.0, "G03", 110),
            ("B03", "G03", 110, 2.0, "G04", 100),
            ("B04", "G04", 100, 3.0, "G05", 120),
            ("B05", "G05", 120, 0.0, "G06", 120),
            ("B06", "G06", 120, -2.0, "G07", 100),
            ("B07", "G07", 100, -3.0, "G08", 80),
            ("B08", "G08", 80, 0.0, None, None),
        ]

        for (
                balise_id,
                track_code,
                line_speed,
                gradient,
                next_track,
                next_speed
        ) in data:
            balise = Balise(
                balise_id=balise_id,
                balise_type="PASSIVE",
                location=f"{track_code}入口",
                track_code=track_code,
                line_speed=line_speed,
                gradient=gradient,
                next_track=next_track,
                next_speed=next_speed
            )

            self.balises[
                balise_id
            ] = balise

    def get_balise_by_track(
        self,
        track_code
    ):

        for balise in (
            self.balises.values()
        ):

            if (
                balise.track_code
                == track_code
            ):
                return balise

        return None

    def get_all_balises(self):

        return list(
            self.balises.values()
        )