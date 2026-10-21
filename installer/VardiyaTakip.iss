; Windows installer for Vardiya Takip (Inno Setup 6).
; Per-user install: no administrator rights needed. Data is never stored in the
; program folder (it lives in %LOCALAPPDATA%\VardiyaTakip), so uninstalling or
; upgrading never touches the records.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C7B3B9E-4F1A-4B7E-9D8A-0E5F3C2A1D11}
AppName=Vardiya Takip
AppVersion={#AppVersion}
AppVerName=Vardiya Takip {#AppVersion}
AppPublisher=Ó'is coffee & eatery
DefaultDirName={localappdata}\Programs\VardiyaTakip
DefaultGroupName=Vardiya Takip
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VardiyaTakip-Kurulum
SetupIconFile=..\vardiya\assets\icon.ico
UninstallDisplayIcon={app}\VardiyaTakip.exe
UninstallDisplayName=Vardiya Takip
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Kısayollar:"

[Files]
Source: "..\dist\VardiyaTakip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; remove files left by an older version so stale libraries never mix with new ones
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Vardiya Takip"; Filename: "{app}\VardiyaTakip.exe"
Name: "{autoprograms}\Vardiya Takip bakım aracı"; Filename: "{app}\VardiyaBakim.exe"; Parameters: "--check"
Name: "{autodesktop}\Vardiya Takip"; Filename: "{app}\VardiyaTakip.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VardiyaTakip.exe"; Description: "Vardiya Takip'i şimdi aç"; Flags: nowait postinstall skipifsilent
