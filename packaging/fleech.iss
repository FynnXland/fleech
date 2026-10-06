; Inno Setup Script fuer Fleech — erzeugt FleechSetup.exe.
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\fleech.iss
; Voraussetzung: dist\Fleech\ (via packaging/build.py) muss existieren.
; Die AppVersion wird vom Build-Skript per /DAppVersion=... uebergeben (Default unten).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "Fleech"
#define AppExeName "Fleech.exe"
#define AppPublisher "Fleech"

[Setup]
AppId={{7E3A9C4F-2B1D-4E8A-9F6C-FLEECHDICT01}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/FynnXland/fleech
AppSupportURL=https://github.com/FynnXland/fleech/issues
AppUpdatesURL=https://github.com/FynnXland/fleech/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir=..\dist
OutputBaseFilename=FleechSetup-{#AppVersion}
SetupIconFile=..\assets\fleech.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-User-Installation ohne UAC: passt zu HKCU-Autostart & %APPDATA%-Settings,
; installiert nach %LocalAppData%\Programs\Fleech, erscheint in der Windows-Suche.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Ein laufendes Fleech blockiert seine eigenen Dateien. Ohne diese drei Zeilen endet
; ein Update in "Datei in Verwendung" bzw. verlangt einen Neustart des Rechners.
; AppMutex ist derselbe Name wie in fleech/singleinstance.py (MUTEX_NAME) — daran
; erkennt Inno die laufende Instanz und schliesst sie (CloseApplications) selbst.
AppMutex=Fleech.SingleInstance
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Fleech beim Anmelden automatisch starten"; GroupDescription: "Autostart:"; Flags: unchecked

[Files]
; Kompletter onedir-Build (EXE + _internal + Assets/Prompts/config.yaml).
Source: "..\dist\Fleech\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Startmenue-Eintrag → in Windows-Suche als "Fleech" auffindbar.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Fleech Diktat-App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Autostart (optional per Task). uninsdeletevalue entfernt ihn bei Deinstallation.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Fleech"; ValueData: """{app}\{#AppExeName}"" --gui"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Description: "{cm:LaunchProgram,Fleech}"; Filename: "{app}\{#AppExeName}"; \
    Flags: nowait postinstall skipifsilent
; Stiller Lauf = Update aus der App heraus ("Installieren und neu starten"). Dann
; MUSS Fleech von allein wiederkommen — sonst waere die App nach dem Update weg.
Filename: "{app}\{#AppExeName}"; Parameters: "--gui"; \
    Flags: nowait skipifnotsilent

[UninstallRun]
; Auch einen zur Laufzeit (im Settings-UI) gesetzten Autostart-Eintrag entfernen.
Filename: "{cmd}"; RunOnceId: "DelFleechAutostart"; Flags: runhidden; \
    Parameters: "/c reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v Fleech /f"

[UninstallDelete]
; Optionale Aufraeumung: die App-eigenen Logs (User-Settings bleiben absichtlich erhalten).
Type: files; Name: "{userappdata}\Fleech\fleech.log"
