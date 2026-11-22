; Glib installer (Inno Setup 6). Built by .github/workflows/windows.yml.
; Installs for the current user only: no administrator rights needed.
; Recordings, voice samples and downloaded voice engines live in %LOCALAPPDATA%\Glib and are
; kept when Glib is uninstalled or updated.

#define AppName "Glib"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E92-9C1A-5D0E7F4B2A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=HRadhi4
AppPublisherURL=https://github.com/HRadhi4/glib
AppSupportURL=https://github.com/HRadhi4/glib/issues
DefaultDirName={localappdata}\Programs\Glib
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GlibSetup-{#AppVersion}
SetupIconFile=..\assets\glib.ico
UninstallDisplayIcon={app}\assets\glib.ico
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
WizardImageFile=wizard.bmp,wizard@2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small@2x.bmp
LicenseFile=..\build\license.txt
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Glib recording app setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; a clean program folder on every update (user data lives elsewhere)
Type: filesandordirs; Name: "{app}\glib"
Type: filesandordirs; Name: "{app}\runtime"

[Files]
Source: "..\build\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Glib"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m glib"; WorkingDir: "{app}"; IconFilename: "{app}\assets\glib.ico"; Comment: "Record narration from a script"
Name: "{autodesktop}\Glib"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m glib"; WorkingDir: "{app}"; IconFilename: "{app}\assets\glib.ico"; Comment: "Record narration from a script"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-m glib"; WorkingDir: "{app}"; Description: "Start Glib now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; stop Glib if it is still running so its files can be removed
; (only Glib's own copy of Python is stopped, never other programs)
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -like '{app}\runtime\*' } | Stop-Process -Force"""; Flags: runhidden; RunOnceId: "StopGlib"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Glib is installed.%n%nThe first time it opens, Glib downloads its voice engines (about 1.2 GB). After that it works without the internet, and nothing you record leaves this computer.
