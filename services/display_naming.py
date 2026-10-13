"""下行线设备和区段的用户可见名称。

业务层始终使用 G01～G38 和 S01～S18 作为稳定内部索引；
界面通过本模块统一转换，避免绘图、限速和状态栏各自维护一套编号。
"""

import re


def track_display_name(track_code):
    if track_code in ("G01", "G02"):
        return "SFLQG"
    if track_code in ("G37", "G38"):
        return "XJG"
    if not isinstance(track_code, str) or not re.fullmatch(r"G\d{2}", track_code):
        return track_code
    number = int(track_code[1:])
    if not 3 <= number <= 36:
        return track_code
    signal_number = 63 + ((number - 3) // 2) * 20
    suffix = "BG" if number % 2 == 1 else "AG"
    return f"{signal_number}{suffix}"


def signal_display_name(signal_id):
    if not isinstance(signal_id, str):
        return signal_id
    match = re.fullmatch(r"S(\d{2})", signal_id)
    if match is None:
        return signal_id
    index = int(match.group(1))
    if not 1 <= index <= 18:
        return signal_id
    return str(63 + (index - 1) * 20)


def block_display_name(block_number):
    if block_number == 1:
        return "SFLQG"
    if block_number == 19:
        return "XJG"
    return f"{63 + (block_number - 2) * 20}G"


def section_selection_rows():
    """返回（显示名，起点内部值，终点内部值）。"""
    rows = [("SFLQG", "G01", "G02")]
    rows.extend(
        (track_display_name(f"G{number:02d}"), f"G{number:02d}", f"G{number:02d}")
        for number in range(3, 37)
    )
    rows.append(("XJG", "G37", "G38"))
    return tuple(rows)


def display_section_range(start_section, end_section):
    start_name = track_display_name(start_section)
    end_name = track_display_name(end_section)
    if start_name == end_name:
        return start_name
    return f"{start_name}～{end_name}"


def replace_internal_names(text):
    """将错误提示中的内部区段/信号编号转换为展示名。"""
    if not isinstance(text, str):
        return text
    text = re.sub(
        r"G\d{2}",
        lambda match: track_display_name(match.group(0)),
        text,
    )
    return re.sub(
        r"S\d{2}",
        lambda match: signal_display_name(match.group(0)),
        text,
    )
