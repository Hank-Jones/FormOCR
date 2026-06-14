; Inno Setup script for FormOCR offline (~2.7 GB). Compile with: iscc scripts\FormOCR-installer.iss
; Requires Inno Setup 6: https://jrsoftware.org/isinfo.php

#define AppVersion "1.0.0"
#ifndef SourceRoot
  #define SourceRoot "..\dist\FormOCR-Offline\app"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName=FormOCR
AppVersion={#AppVersion}
AppPublisher=FormOCR
DefaultDirName={autopf}\FormOCR
DefaultGroupName=FormOCR
OutputDir=..\dist\FormOCR-Offline
OutputBaseFilename=FormOCR-Setup
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
SetupIconFile=..\..\apps\desktop\src-tauri\icons\icon.ico
UninstallDisplayIcon={app}\formocr-desktop.exe

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FormOCR"; Filename: "{app}\formocr-desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FormOCR.ico"
Name: "{autodesktop}\FormOCR"; Filename: "{app}\formocr-desktop.exe"; WorkingDir: "{app}"; IconFilename: "{app}\FormOCR.ico"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-formocr.ps1"" -InstallDir ""{app}"" -SeedOnly"; StatusMsg: "Preparing offline models..."
Filename: "{app}\formocr-desktop.exe"; Description: "Launch FormOCR"; Flags: postinstall nowait
