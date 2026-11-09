; telltale.iss
; Inno Setup script: turns the PyInstaller output (dist\telltale\) into a
; Windows installer, dist\Telltale-Analysis-<version>-Setup.exe.
;
; Build (from the repo root, after running PyInstaller):
;   ISCC.exe /DAppVersion=1.1.0 packaging\windows\telltale.iss
; Paths below are relative to this file.

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "Telltale Analysis"
#define AppExe "telltale.exe"

[Setup]
; Identifies the app for upgrades and uninstalling. Never change it.
AppId={{26CEC795-2FD5-4428-BCDC-668E60E8EAEA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=afewsmallchanges
AppPublisherURL=https://github.com/afewsmallchanges/video-review
AppSupportURL=https://github.com/afewsmallchanges/video-review/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; the user can choose
; "all users" instead (which asks for admin).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=Telltale-Analysis-{#AppVersion}-Setup
SetupIconFile=..\icons\telltale.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\telltale\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Uninstalling leaves imported clips and projects in %LOCALAPPDATA%\telltale
; on purpose, so reinstalling or upgrading never loses work.
