from models.balise import Balise


class PassiveBaliseService:

    def __init__(self):

        self.balises = {}

        self.create_default_balises()

    def create_default_balises(self):

        data = []
        for index in range(1, 39):
            next_track = f"G{index + 1:02d}" if index < 38 else None
            next_speed = 120 if next_track is not None else None
            data.append(
                (f"B{index:02d}", f"G{index:02d}", 120, 0.0, next_track, next_speed)
            )

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
