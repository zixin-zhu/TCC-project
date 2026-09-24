import sys

from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    # 单窗口双TCC：TCC_A与TCC_B同窗共存，
    # 两者通过本机TCP互联
    window = MainWindow()

    window.show()

    sys.exit(
        app.exec_()
    )
