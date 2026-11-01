"""Know Signal desktop launcher (the KnowSignal.exe entry point).

  KnowSignal.exe             start the quiz server and open the host screen in its own window
  KnowSignal.exe --no-window start the server only (testing)
  KnowSignal.exe --setup     one-time machine setup (run elevated by the installer)
  KnowSignal.exe --unsetup   undo setup (run by the uninstaller)

The host screen opens in a dedicated Microsoft Edge app window (Edge's engine ships with
Windows 10/11). Closing that window quits Know Signal.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "KnowSignal")
os.makedirs(STATE_DIR, exist_ok=True)
logging.basicConfig(filename=os.path.join(STATE_DIR, "knowsignal.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("knowsignal")


def message_box(text, title="Know Signal", error=False):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    except Exception:
        print(text)


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(path):
                return path
    return None


def running_instance():
    """URL of an already-running Know Signal on this laptop, if any."""
    for port in (80, 8080, 8000):
        url = f"http://127.0.0.1:{port}" if port != 80 else "http://127.0.0.1"
        try:
            with urllib.request.urlopen(url + "/api/info", timeout=0.6) as r:
                if r.headers.get("Server", "").startswith("KnowSignal"):
                    json.loads(r.read())
                    return url
        except Exception:
            continue
    return None


def open_window(url):
    """Open the host screen in an Edge app window; returns the process (or None for a plain browser)."""
    edge = find_edge()
    if not edge:
        webbrowser.open(url)
        return None
    profile = os.path.join(STATE_DIR, "window")
    args = [edge, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required", "--disable-features=Translate", "--start-maximized"]
    return subprocess.Popen(args)


def run_app(show_window=True):
    existing = running_instance()
    if existing:
        log.info("already running at %s; opening another window", existing)
        open_window(existing + "/host")
        return 0

    import server
    httpd = server.create_server()
    if not httpd:
        message_box("Know Signal couldn't start: ports 80, 8080 and 8000 are all busy.\n"
                    "Close other servers and try again.", error=True)
        return 1
    port = httpd.server_address[1]
    url = "http://localhost" + ("" if port == 80 else f":{port}")
    log.info("serving on %s (quizzes: %s)", url, server.QUIZ_DIR)
    serving = threading.Thread(target=httpd.serve_forever, daemon=True)
    serving.start()

    window = open_window(url + "/host") if show_window else None
    if window is None:
        # Plain browser fallback (or --no-window): serve until the host presses Quit on the setup screen.
        serving.join()
        return 0
    # A dedicated Edge profile keeps this process alive exactly as long as the window is open.
    while window.poll() is None and serving.is_alive():
        time.sleep(0.5)
    log.info("window closed; shutting down")
    httpd.shutdown()
    return 0


def main():
    args = sys.argv[1:]
    exe = sys.executable if getattr(sys, "frozen", False) else None
    if "--setup" in args or "--unsetup" in args:
        import windows_setup
        lines = []
        code = (windows_setup.run_unsetup(lines.append) if "--unsetup" in args
                else windows_setup.run_setup(program=exe, log=lines.append))
        log.info("setup result %s: %s", code, " | ".join(lines))
        if code and "--quiet" not in args:
            message_box("Know Signal setup finished with a problem:\n\n" + "\n".join(lines) +
                        "\n\nThe quiz will still run on an existing Wi-Fi network.", error=True)
        return code
    try:
        return run_app(show_window="--no-window" not in args)
    except Exception:
        log.exception("crashed")
        message_box("Know Signal hit an unexpected error. Details are in:\n" +
                    os.path.join(STATE_DIR, "knowsignal.log"), error=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
