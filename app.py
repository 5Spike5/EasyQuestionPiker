import sys

from question_viewer.ui import run
from question_viewer.webview_host import main as run_webview_host


if __name__ == "__main__":
    if "--webview-host" in sys.argv[1:]:
        run_webview_host(sys.argv[1:])
    else:
        run()
