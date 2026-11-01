"""Control the Windows Mobile Hotspot (status / start / stop), including with no internet.

Uses the Windows Runtime tethering API through Windows PowerShell 5.1, which ships with
every Windows 10/11 machine. Arguments travel in environment variables to avoid quoting issues.
"""

import json
import os
import subprocess

_PS = r"""
$ErrorActionPreference = 'Stop'
function Out($o) { $o | ConvertTo-Json -Compress; exit 0 }
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $NI = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
  $TM = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
  $RT = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
  $ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
  $asOp = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
  $asAct = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
  function AwaitOp($op) { $t = $asOp.MakeGenericMethod($RT).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
  function AwaitAct($a) { $t = $asAct.Invoke($null, @($a)); $t.Wait(-1) | Out-Null }

  $wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.PhysicalMediaType -match '802\.11' }
  if (-not $wifi) { Out @{ ok = $false; state = 'unavailable'; reason = "This laptop's Wi-Fi is off or missing. Turn Wi-Fi on (it doesn't need to connect to anything)." } }

  $Enabled = [Windows.Networking.NetworkOperators.TetheringCapability]::Enabled
  $share = $null; $why = ''
  $inet = $NI::GetInternetConnectionProfile()
  if ($inet -and $TM::GetTetheringCapabilityFromConnectionProfile($inet) -eq $Enabled) { $share = $inet; $why = 'internet' }
  if (-not $share) {
    $loopIds = @(Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceDescription -like '*KM-TEST Loopback*' } | ForEach-Object { $_.InterfaceGuid.Trim('{}').ToLower() })
    $cands = @($NI::GetConnectionProfiles() | Where-Object { $_.NetworkAdapter -and $TM::GetTetheringCapabilityFromConnectionProfile($_) -eq $Enabled })
    $share = $cands | Where-Object { $loopIds -contains $_.NetworkAdapter.NetworkAdapterId.ToString().ToLower() } | Select-Object -First 1
    if ($share) { $why = 'offline' } elseif ($cands) { $share = $cands[0]; $why = 'other' }
  }
  if (-not $share) { Out @{ ok = $false; state = 'unavailable'; reason = 'Windows has no connection it can share. Re-run the Know Signal installer (it adds a virtual adapter that fixes this).' } }

  $mgr = $null
  try { $mgr = $TM::CreateFromConnectionProfile($share) } catch {
    try { Start-Service icssvc -ErrorAction Stop; Start-Sleep -Seconds 2; $mgr = $TM::CreateFromConnectionProfile($share) } catch {
      Out @{ ok = $false; state = 'unavailable'; reason = 'The Windows Mobile Hotspot service is not running. Open Settings > Network & internet > Mobile hotspot once, then try again.' } } }

  $action = $env:KS_ACTION
  if ($action -eq 'stop' -and "$($mgr.TetheringOperationalState)" -eq 'On') { AwaitOp ($mgr.StopTetheringAsync()) | Out-Null }
  if ($action -eq 'start') {
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    $ssid = $env:KS_SSID; $pw = $env:KS_PW
    if ($ssid -and $pw -and ($cfg.Ssid -ne $ssid -or $cfg.Passphrase -ne $pw)) {
      if ("$($mgr.TetheringOperationalState)" -eq 'On') { AwaitOp ($mgr.StopTetheringAsync()) | Out-Null }
      $cfg.Ssid = $ssid; $cfg.Passphrase = $pw
      AwaitAct ($mgr.ConfigureAccessPointAsync($cfg))
    }
    if ("$($mgr.TetheringOperationalState)" -ne 'On') {
      $r = AwaitOp ($mgr.StartTetheringAsync())
      if ("$($r.Status)" -ne 'Success') { Out @{ ok = $false; state = 'off'; reason = "Windows refused to start the hotspot ($($r.Status)). Try Settings > Network & internet > Mobile hotspot." } }
    }
  }
  $cfg = $mgr.GetCurrentAccessPointConfiguration()
  Out @{ ok = $true; state = $(if ("$($mgr.TetheringOperationalState)" -eq 'On') { 'on' } else { 'off' });
         ssid = $cfg.Ssid; password = $cfg.Passphrase; clients = $mgr.ClientCount; max = $mgr.MaxClientCount; sharing = $why }
} catch {
  Out @{ ok = $false; state = 'unavailable'; reason = "$($_.Exception.Message)" }
}
"""


def _run(action, ssid="", password="", timeout=45):
    if os.name != "nt":
        return {"ok": False, "state": "unavailable", "reason": "The hotspot switch only works on Windows."}
    env = dict(os.environ, KS_ACTION=action, KS_SSID=ssid or "", KS_PW=password or "")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-Command", _PS], capture_output=True, text=True, timeout=timeout, env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip().startswith("{")]
        return json.loads(lines[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
        return {"ok": False, "state": "unavailable", "reason": f"Couldn't talk to the Windows hotspot: {e}"}


def status():
    return _run("status", timeout=20)


def start(ssid, password):
    if password and len(password) < 8:
        return {"ok": False, "state": "off", "reason": "The Wi-Fi password needs at least 8 characters."}
    return _run("start", ssid, password)


def stop():
    return _run("stop")
