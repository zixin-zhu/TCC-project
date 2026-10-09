class TemporarySpeedService:
    """管理按连续轨道区段设置的临时限速。"""

    def __init__(self, section_order):
        self.section_order = list(section_order)
        self._section_index = {
            section_id: index for index, section_id in enumerate(self.section_order)
        }
        self._restrictions = {}
        self._next_number = 1

    def set_restriction(self, start_section, end_section, speed_kmh):
        if start_section not in self._section_index or end_section not in self._section_index:
            raise ValueError("限速区段不存在")
        if self._section_index[start_section] > self._section_index[end_section]:
            raise ValueError("起始区段不能位于终止区段之后")
        speed = int(speed_kmh)
        if speed <= 0:
            raise ValueError("限速值必须大于 0")
        restriction_id = f"TSR-{self._next_number:03d}"
        self._next_number += 1
        restriction = {
            "id": restriction_id,
            "start_section": start_section,
            "end_section": end_section,
            "speed_kmh": speed,
            "active": True,
        }
        self._restrictions[restriction_id] = restriction
        return dict(restriction)

    def cancel_restriction(self, restriction_id):
        restriction = self._restrictions.get(restriction_id)
        if restriction is None or not restriction["active"]:
            return False
        restriction["active"] = False
        return True

    def active_restrictions(self):
        return [
            dict(restriction)
            for restriction in self._restrictions.values()
            if restriction["active"]
        ]

    def speed_for(self, section_id):
        if section_id not in self._section_index:
            return None
        section_index = self._section_index[section_id]
        speeds = []
        for restriction in self._restrictions.values():
            if not restriction["active"]:
                continue
            start_index = self._section_index[restriction["start_section"]]
            end_index = self._section_index[restriction["end_section"]]
            if start_index <= section_index <= end_index:
                speeds.append(restriction["speed_kmh"])
        return min(speeds) if speeds else None
