#ifndef PackageRoot
  #error PackageRoot must point to the verified package payload
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ArtifactDirectory
  #error ArtifactDirectory is required
#endif

[Setup]
AppId={{640F2B9B-B48D-4C30-8ED1-FCFF5C8BB1C4}
AppName=CyDecompilator
AppVersion={#AppVersion}
AppPublisher=Cyberalien
AppPublisherURL=https://github.com/MrMybal/CyDecompilator
AppSupportURL=https://github.com/MrMybal/CyDecompilator/issues
AppUpdatesURL=https://github.com/MrMybal/CyDecompilator/releases
DefaultDirName={localappdata}\Programs\CyDecompilator
DefaultGroupName=CyDecompilator
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#PackageRoot}\LICENSE
OutputDir={#ArtifactDirectory}
OutputBaseFilename=CyDecompilator-{#AppVersion}-windows-x64-setup
SetupIconFile={#PackageRoot}\app\assets\cydecompilator.ico
UninstallDisplayIcon={app}\CyDecompilator.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CyDecompilator"; Filename: "{app}\CyDecompilator.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\CyDecompilator"; Filename: "{app}\CyDecompilator.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Documentation"; Filename: "{app}\app\Documentation\Documentation.html"
Name: "{group}\{cm:UninstallProgram,CyDecompilator}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\CyDecompilator.exe"; Description: "{cm:LaunchProgram,CyDecompilator}"; Flags: nowait postinstall skipifsilent

; Deliberately no recursive uninstall deletion: projects, settings, downloaded engines
; and other files created after installation are retained by Inno's normal file log.
