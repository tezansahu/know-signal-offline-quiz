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


def wait_until_ready(url, timeout=10):
    """True once the server answers on the loopback address the window will use."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


# How long to keep serving after the last host/editor screen disconnects (covers page reloads
# and moving between the host screen and the editor), and how long to wait for the first one.
IDLE_GRACE = 15
FIRST_CONNECT_GRACE = 120


def run_app(show_window=True):
    log.info("starting %s (frozen=%s)", sys.executable, getattr(sys, "frozen", False))
    existing = running_instance()
    if existing:
        log.info("already running at %s; opening another window", existing)
        open_window(existing + "/host")
        return 0

    import server
    httpd = server.create_server()
    if not httpd:
        log.error("no free port among 80/8080/8000")
        message_box("Know Signal couldn't start: ports 80, 8080 and 8000 are all busy.\n"
                    "Close other servers and try again.", error=True)
        return 1
    port = httpd.server_address[1]
    # 127.0.0.1, not "localhost": avoids the browser trying IPv6 (::1) where we don't listen.
    url = "http://127.0.0.1" + ("" if port == 80 else f":{port}")
    log.info("serving on %s (quizzes: %s)", url, server.QUIZ_DIR)
    serving = threading.Thread(target=httpd.serve_forever, daemon=True)
    serving.start()
    if not wait_until_ready(url):
        log.error("server did not answer on %s", url)
        message_box(f"Know Signal started but isn't reachable at {url}.\n"
                    "Security software may be blocking it. Details:\n" +
                    os.path.join(STATE_DIR, "knowsignal.log"), error=True)
        httpd.shutdown()
        return 1

    if not show_window:
        serving.join()
        return 0
    window = open_window(url + "/host")
    log.info("window launched (%s)", "edge pid %s" % window.pid if window else "default browser")

    # Lifetime follows the host screen's live connection, not the browser process: Edge may hand
    # the window to another process (first-run relaunch, startup boost, policies), so its PID is
    # not a reliable "window is open" signal.
    started, seen, idle_since = time.time(), False, None
    while serving.is_alive():
        time.sleep(1)
        if window is not None and window.poll() is not None and not seen:
            log.info("edge launcher exited with %s before the page connected", window.returncode)
            window = None
        if server.HUB.hosts:
            seen, idle_since = True, None
            continue
        if not seen:
            if time.time() - started > FIRST_CONNECT_GRACE:
                log.warning("no host screen connected within %ss; shutting down", FIRST_CONNECT_GRACE)
                break
            continue
        idle_since = idle_since or time.time()
        if time.time() - idle_since > IDLE_GRACE:
            log.info("host screen closed; shutting down")
            break
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
