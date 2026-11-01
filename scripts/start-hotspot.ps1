<#
.SYNOPSIS
  Starts (or stops) the Windows Mobile Hotspot for Know Signal - works with no internet.

.EXAMPLE
  .\start-hotspot.ps1                      # uses name/password from config.json (set on the host screen)
  .\start-hotspot.ps1 -Ssid QuizTime -Password quiz1234
  .\start-hotspot.ps1 -Status              # show what would be shared, change nothing
  .\start-hotspot.ps1 -Stop
#>
param(
    [string]$Ssid,
    [string]$Password,
    [switch]$Stop,
    [switch]$Status
)

# The Windows Runtime APIs used here are only available in Windows PowerShell 5.1.
if ($PSVersionTable.PSEdition -eq "Core") {
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    foreach ($kv in $PSBoundParameters.GetEnumerator()) {
        if ($kv.Value -is [switch]) { if ($kv.Value) { $argList += "-$($kv.Key)" } }
        else { $argList += "-$($kv.Key)", "$($kv.Value)" }
    }
    & powershell.exe @argList
    exit $LASTEXITCODE
}

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]

$asTaskOp = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq "IAsyncAction" } | Select-Object -First 1

function Await-Op($op, [Type]$resultType) {
    $task = $asTaskOp.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
function Await-Action($action) {
    $task = $asTaskAction.Invoke($null, @($action))
    $task.Wait(-1) | Out-Null
}

$TM = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]
$NI = [Windows.Networking.Connectivity.NetworkInformation]
$Enabled = [Windows.Networking.NetworkOperators.TetheringCapability]::Enabled

# Pick a connection to "share": real internet if present, otherwise the loopback adapter
# (or any adapter Windows allows) so the hotspot can run fully offline.
function Get-ShareProfile {
    $inet = $NI::GetInternetConnectionProfile()
    if ($inet -and $TM::GetTetheringCapabilityFromConnectionProfile($inet) -eq $Enabled) {
        return @{ Profile = $inet; Why = "internet connection" }
    }
    $loopIds = @(Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceDescription -like "*KM-TEST Loopback*" } |
        ForEach-Object { $_.InterfaceGuid.Trim("{}").ToLower() })
    $candidates = @($NI::GetConnectionProfiles() | Where-Object {
        $_.NetworkAdapter -and $TM::GetTetheringCapabilityFromConnectionProfile($_) -eq $Enabled })
    $loop = $candidates | Where-Object { $loopIds -contains $_.NetworkAdapter.NetworkAdapterId.ToString().ToLower() } |
        Select-Object -First 1
    if ($loop) { return @{ Profile = $loop; Why = "loopback adapter (offline mode)" } }
    if ($candidates) { return @{ Profile = $candidates[0]; Why = "adapter '$($candidates[0].ProfileName)'" } }
    return $null
}

$wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.PhysicalMediaType -match "802\.11" }
if (-not $wifi) {
    Write-Host "No Wi-Fi adapter found (or Wi-Fi is switched off). Turn Wi-Fi on, then try again." -ForegroundColor Red
    exit 1
}
if ((Get-Service WlanSvc).Status -ne "Running") {
    try { Start-Service WlanSvc -ErrorAction Stop } catch {
        Write-Host "The WLAN AutoConfig service is stopped. Run this script as Administrator." -ForegroundColor Red
        exit 1
    }
}

$share = Get-ShareProfile
if (-not $share) {
    Write-Host "No connection that Windows can share was found." -ForegroundColor Red
    Write-Host "Run setup-once.ps1 as Administrator to add the Microsoft Loopback Adapter, then try again."
    exit 1
}
$mgr = $null
for ($i = 0; $i -lt 2 -and -not $mgr; $i++) {
    try { $mgr = $TM::CreateFromConnectionProfile($share.Profile) }
    catch {
        if ($i -gt 0) { throw }
        # The Mobile Hotspot service (icssvc) is demand-started; wake it up.
        try { Start-Service icssvc -ErrorAction Stop }
        catch {
            Write-Host "The Mobile Hotspot service is stopped. Run this script as Administrator once, or toggle" -ForegroundColor Red
            Write-Host "Settings > Network & internet > Mobile hotspot on and off, then try again."
            exit 1
        }
        Start-Sleep -Seconds 2
    }
}
$state = $mgr.TetheringOperationalState
$cfg = $mgr.GetCurrentAccessPointConfiguration()

if ($Status) {
    Write-Host "Would share : $($share.Why)"
    Write-Host "Hotspot     : $state"
    Write-Host "Name        : $($cfg.Ssid)"
    Write-Host "Connected   : $($mgr.ClientCount) / $($mgr.MaxClientCount)"
    exit 0
}

if ($Stop) {
    $r = Await-Op ($mgr.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
    Write-Host "Hotspot stop: $($r.Status)"
    exit 0
}

if (-not $Ssid -or -not $Password) {
    $cfgPath = Join-Path $PSScriptRoot "..\config.json"
    if (Test-Path $cfgPath) {
        $saved = Get-Content $cfgPath -Raw | ConvertFrom-Json
        if (-not $Ssid) { $Ssid = $saved.ssid }
        if (-not $Password) { $Password = $saved.password }
    }
}

if ($Ssid -and $Password) {
    if ($Password.Length -lt 8) { Write-Host "Password must be at least 8 characters." -ForegroundColor Red; exit 1 }
    if ($cfg.Ssid -ne $Ssid -or $cfg.Passphrase -ne $Password) {
        if ($state -eq "On") {
            Await-Op ($mgr.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]) | Out-Null
        }
        $cfg.Ssid = $Ssid
        $cfg.Passphrase = $Password
        Await-Action ($mgr.ConfigureAccessPointAsync($cfg))
        $state = "Off"
    }
}

if ($state -ne "On") {
    $r = Await-Op ($mgr.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
    if ($r.Status -ne "Success") {
        Write-Host "Could not start the hotspot: $($r.Status) $($r.AdditionalErrorMessage)" -ForegroundColor Red
        Write-Host "Try: Settings > Network & internet > Mobile hotspot, and switch it on by hand."
        exit 1
    }
}

$cfg = $mgr.GetCurrentAccessPointConfiguration()
# Remember the details so the quiz lobby can show a "Join Wi-Fi" QR code.
try {
    @{ ssid = $cfg.Ssid; password = $cfg.Passphrase } | ConvertTo-Json |
        Set-Content -Path (Join-Path $PSScriptRoot "..\config.json") -Encoding UTF8
} catch { }
Write-Host "`nHotspot is ON (sharing $($share.Why))" -ForegroundColor Green
Write-Host "  Wi-Fi name : $($cfg.Ssid)"
Write-Host "  Password   : $($cfg.Passphrase)"
Write-Host "  Max devices: $($mgr.MaxClientCount)"
Write-Host "  Players open http://192.168.137.1 once connected.`n"
