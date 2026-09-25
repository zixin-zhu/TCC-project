"""旧入口兼容层；正式装配统一委托给 run.py。"""

import sys

from run import main


if __name__ == "__main__":
    station = sys.argv[1].upper() if len(sys.argv) > 1 else "A"
    raise SystemExit(main(["--station", station]))
