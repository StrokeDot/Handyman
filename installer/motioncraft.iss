; Per-user installer: no admin rights needed, so updates install without prompts.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "MotionCraft"
; the app's earlier name: its program folder and shortcuts are removed on update
#define OldAppName "Handyman"

[Setup]
AppId={{6F1E5C2A-4B7D-4C8E-9A51-3D2B7E0F9C14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
; same AppId as Handyman, so this is an update; but install into the new MotionCraft folder
UsePreviousAppDir=no
UsePreviousGroup=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; Remove the previous version's program files (your books and settings live elsewhere and stay).
Type: filesandordirs; Name: "{app}\_internal"
; the old Handyman program folder and shortcuts (the app also tidies these on its first start)
Type: filesandordirs; Name: "{localappdata}\Programs\{#OldAppName}"
Type: files; Name: "{autoprograms}\{#OldAppName}.lnk"
Type: files; Name: "{autodesktop}\{#OldAppName}.lnk"

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppName}.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppName}.exe"; Tasks: desktopicon

[Run]
; Starts the app after installing, also after a silent update from inside the app.
Filename: "{app}\{#MyAppName}.exe"; Description: "Start {#MyAppName}"; Flags: nowait postinstall
