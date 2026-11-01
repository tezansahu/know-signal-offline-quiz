<#
.SYNOPSIS
  Build the Know Signal Windows installer: dist\KnowSignal-Setup-<version>.exe

.EXAMPLE
  .\packaging\build.ps1 -Version 1.0.0

  Needs Python 3.9+ and Inno Setup 6 (winget install JRSoftware.InnoSetup).
#>
param([string]$Version = "1.0.0")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

Write-Host "1/4  Tooling" -ForegroundColor Cyan
python -m pip install --quiet --disable-pip-version-check pyinstaller pillow
if ($LASTEXITCODE) { throw "pip install failed" }

Write-Host "2/4  Icon" -ForegroundColor Cyan
New-Item -ItemType Directory -Force build | Out-Null
python packaging\make_icon.py build\knowsignal.ico

Write-Host "3/4  App (PyInstaller)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --windowed --name KnowSignal `
  --icon "$root\build\knowsignal.ico" `
  --add-data "$root\src\static;static" `
  --add-data "$root\quizzes\sample-ai-basics.json;quizzes" `
  --distpath "$root\build\dist" --workpath "$root\build\work" --specpath "$root\build" `
  "$root\src\app.py"
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Write-Host "4/4  Installer (Inno Setup)" -ForegroundColor Cyan
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$Version" "$root\packaging\installer.iss"
if ($LASTEXITCODE) { throw "Inno Setup failed" }

$out = Get-Item "$root\dist\KnowSignal-Setup-$Version.exe"
Write-Host ("`nBuilt {0} ({1:N1} MB)" -f $out.FullName, ($out.Length / 1MB)) -ForegroundColor Green
