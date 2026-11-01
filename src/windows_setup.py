"""One-time Windows machine setup for Know Signal. Must run as Administrator.

  KnowSignal.exe --setup       (run by the installer)
  KnowSignal.exe --unsetup     (run by the uninstaller)

Steps:
  1. Raise the Mobile Hotspot device limit from 8 to 128 (registry: icssvc WifiMaxPeers).
  2. Allow Know Signal through Windows Firewall on all network types.
  3. Add the Microsoft KM-TEST Loopback Adapter, a built-in virtual network card that lets
     Windows start a hotspot when the laptop has no internet. Uses the same SetupAPI calls
     as Microsoft's `devcon install`.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

FIREWALL_RULE = "Know Signal"
LEGACY_RULE = "Offline Quiz (TCP 80, 8080)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- hotspot limit
def raise_hotspot_limit(peers=128):
    import winreg
    key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Services\icssvc\Settings", 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "WifiMaxPeers", 0, winreg.REG_DWORD, peers)
    winreg.CloseKey(key)
    _run(["powershell.exe", "-NoProfile", "-Command", "Restart-Service icssvc -Force -ErrorAction SilentlyContinue"])
    return f"Hotspot device limit raised to {peers}"


# ---------------------------------------------------------------- firewall
def allow_firewall(program):
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"])
    if program:
        code, out = _run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}", "dir=in",
                          "action=allow", f"program={program}", "enable=yes", "profile=any"])
    else:
        code, out = _run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}", "dir=in",
                          "action=allow", "protocol=TCP", "localport=80,8080,8000", "enable=yes", "profile=any"])
    if code:
        raise RuntimeError(f"firewall: {out}")
    return "Firewall allows Know Signal on all networks"


def remove_firewall():
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"])
    return "Firewall rule removed"


# ---------------------------------------------------------------- loopback adapter
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID),
                ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


def loopback_present():
    code, out = _run(["powershell.exe", "-NoProfile", "-Command",
                      "@(Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue | "
                      "Where-Object { $_.InterfaceDescription -like '*KM-TEST Loopback*' }).Count"])
    try:
        return int(out.splitlines()[-1]) > 0
    except (ValueError, IndexError):
        return False


def add_loopback_adapter():
    if loopback_present():
        return "Virtual network adapter already present"
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    newdev = ctypes.WinDLL("newdev", use_last_error=True)
    inf = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "inf", "netloop.inf")
    hwid = "*MSLOOP"

    class_guid = GUID()
    class_name = ctypes.create_unicode_buffer(256)
    if not setupapi.SetupDiGetINFClassW(inf, ctypes.byref(class_guid), class_name, 256, None):
        raise ctypes.WinError(ctypes.get_last_error())

    setupapi.SetupDiCreateDeviceInfoList.restype = ctypes.c_void_p
    devs = setupapi.SetupDiCreateDeviceInfoList(ctypes.byref(class_guid), None)
    if devs in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = SP_DEVINFO_DATA()
        info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        DICD_GENERATE_ID = 0x1
        if not setupapi.SetupDiCreateDeviceInfoW(ctypes.c_void_p(devs), class_name, ctypes.byref(class_guid),
                                                 None, None, DICD_GENERATE_ID, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        ids = (hwid + "\0\0").encode("utf-16-le")
        SPDRP_HARDWAREID = 0x1
        if not setupapi.SetupDiSetDeviceRegistryPropertyW(ctypes.c_void_p(devs), ctypes.byref(info), SPDRP_HARDWAREID,
                                                          ids, len(ids)):
            raise ctypes.WinError(ctypes.get_last_error())
        DIF_REGISTERDEVICE = 0x19
        if not setupapi.SetupDiCallClassInstaller(DIF_REGISTERDEVICE, ctypes.c_void_p(devs), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(ctypes.c_void_p(devs))

    reboot = wintypes.BOOL(False)
    INSTALLFLAG_FORCE = 0x1
    if not newdev.UpdateDriverForPlugAndPlayDevicesW(None, hwid, inf, INSTALLFLAG_FORCE, ctypes.byref(reboot)):
        raise ctypes.WinError(ctypes.get_last_error())
    return "Virtual network adapter added (lets the hotspot run with no internet)"


# ---------------------------------------------------------------- entry points
def run_setup(program=None, log=print):
    if not is_admin():
        log("Setup needs administrator rights.")
        return 1
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={LEGACY_RULE}"])
    failures = 0
    for step in (raise_hotspot_limit, lambda: allow_firewall(program), add_loopback_adapter):
        try:
            log("[ok] " + step())
        except Exception as e:  # keep going; each step is independent
            failures += 1
            log(f"[!!] {e}")
    return 1 if failures else 0


def run_unsetup(log=print):
    log("[ok] " + remove_firewall())
    return 0


if __name__ == "__main__":
    if "--unsetup" in sys.argv:
        sys.exit(run_unsetup())
    sys.exit(run_setup(program=None))
