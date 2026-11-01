#Requires -RunAsAdministrator
<#
.SYNOPSIS
  One-time laptop setup for Know Signal. Run once at home, as Administrator.

.DESCRIPTION
  1. Raises the Windows Mobile Hotspot device limit from 8 (WifiMaxPeers).
  2. Opens the quiz ports (80, 8080) in Windows Firewall for all network types.
  3. Checks for the Microsoft Loopback Adapter, which lets the hotspot start
     when the laptop has no internet, and walks you through adding it if missing.
#>
param([int]$MaxPeers = 128)

$ErrorActionPreference = "Stop"
Write-Host "`nKnow Signal - one-time setup`n" -ForegroundColor Cyan

# 1. Hotspot device limit
$key = "HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings"
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
New-ItemProperty -Path $key -Name WifiMaxPeers -PropertyType DWord -Value $MaxPeers -Force | Out-Null
Write-Host "[ok] Hotspot device limit set to $MaxPeers" -ForegroundColor Green
try {
    Restart-Service icssvc -Force -ErrorAction Stop
    Write-Host "[ok] Restarted the Mobile Hotspot service"
} catch {
    Write-Host "[..] Mobile Hotspot service will pick up the new limit after a reboot"
}

# 2. Firewall
$rule = "Offline Quiz (TCP 80, 8080)"
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort 80, 8080 `
    -Action Allow -Profile Any | Out-Null
Write-Host "[ok] Firewall allows quiz traffic on ports 80 and 8080" -ForegroundColor Green

# 3. Loopback adapter (lets the hotspot run with no internet at all)
$loop = Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceDescription -like "*KM-TEST Loopback*" }
if ($loop) {
    Write-Host "[ok] Loopback adapter present: $($loop.Name)" -ForegroundColor Green
} else {
    Write-Host "`n[!!] Loopback adapter not found. Adding it takes about a minute:" -ForegroundColor Yellow
    Write-Host @"
     The 'Add Hardware' wizard is opening now. In it:
       Next  ->  'Install the hardware that I manually select from a list'  ->  Next
       'Network adapters'  ->  Next
       Manufacturer: Microsoft   Model: Microsoft KM-TEST Loopback Adapter  ->  Next -> Next -> Finish
     Then run this script again to confirm.
"@
    Start-Process hdwwiz.exe
}

# Python check
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Write-Host "[ok] $(& python --version 2>&1)" -ForegroundColor Green }
else { Write-Host "[!!] Python not found. Install Python 3.9+ from python.org (tick 'Add to PATH')." -ForegroundColor Yellow }

Write-Host "`nDone. On the day, run scripts\start-hotspot.ps1, then scripts\start-quiz.bat.`n" -ForegroundColor Cyan
