import sys

from PyQt5.QtWidgets import QApplication

from ui.station_window import StationWindow


if __name__ == "__main__":

    app = QApplication(sys.argv)

    # 默认启动A站
    station_type = "A"

    # 读取启动参数
    if len(sys.argv) > 1:

        station_type = (
            sys.argv[1]
            .upper()
        )

    # 参数检查
    if station_type not in ["A", "B"]:

        print(
            "启动参数错误，请使用："
        )

        print(
            "python main.py A"
        )

        print(
            "或"
        )

        print(
            "python main.py B"
        )

        sys.exit(1)

    window = StationWindow(
        station_type
    )

    window.show()

    sys.exit(
        app.exec_()
    )