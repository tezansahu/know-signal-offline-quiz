; Know Signal installer (Inno Setup 6). Built by packaging\build.ps1.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F3A9C2E-4B7D-4E51-9A0C-3D8E2F1B7A64}
AppName=Know Signal
AppVersion={#AppVersion}
AppVerName=Know Signal {#AppVersion}
AppPublisher=Tezan Sahu
AppComments=Out of range. Never out of answers.
DefaultDirName={autopf}\Know Signal
DefaultGroupName=Know Signal
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=KnowSignal-Setup-{#AppVersion}
SetupIconFile=..\build\knowsignal.ico
UninstallDisplayIcon={app}\KnowSignal.exe
UninstallDisplayName=Know Signal
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\dist\KnowSignal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Know Signal"; Filename: "{app}\KnowSignal.exe"; Comment: "Out of range. Never out of answers."
Name: "{autodesktop}\Know Signal"; Filename: "{app}\KnowSignal.exe"; Tasks: desktopicon

[Run]
; One-time machine setup: hotspot limit, firewall rule, offline virtual adapter. Needs admin, which setup already has.
Filename: "{app}\KnowSignal.exe"; Parameters: "--setup"; StatusMsg: "Preparing this laptop to host quizzes without internet..."; Flags: waituntilterminated
Filename: "{app}\KnowSignal.exe"; Description: "Launch Know Signal"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\KnowSignal.exe"; Parameters: "--unsetup --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "KnowSignalUnsetup"
