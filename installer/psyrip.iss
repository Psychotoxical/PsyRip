; Inno-Setup-Skript für psyrip – wird von build.bat aufgerufen (ISCC /DAppVersion=x.y.z installer\psyrip.iss).
; Installiert den kompletten PyInstaller-Ordner dist\psyrip inklusive bin\ffmpeg.exe/ffprobe.exe:
; nach der Installation ist nichts nachzuinstallieren.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B3C1E7A2-5D4F-4E8B-9A61-2F7C0D9E4A13}
AppName=psyrip
AppVersion={#AppVersion}
AppVerName=psyrip {#AppVersion}
AppPublisher=psyrip
DefaultDirName={autopf}\psyrip
DefaultGroupName=psyrip
DisableProgramGroupPage=yes
; Standard: ohne Admin-Rechte für den aktuellen Benutzer; im Dialog wählbar „für alle Benutzer“
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\installer_out
OutputBaseFilename=psyrip-setup-{#AppVersion}
SetupIconFile=..\psyrip\assets\psyrip.ico
UninstallDisplayIcon={app}\psyrip.exe
UninstallDisplayName=psyrip {#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
; eigener 64-Bit-Prozess für LZMA – sonst „Out of memory“ im 32-Bit-Compiler bei ~350 MB Eingabe
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\psyrip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\psyrip"; Filename: "{app}\psyrip.exe"
Name: "{autodesktop}\psyrip"; Filename: "{app}\psyrip.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\psyrip.exe"; Description: "{cm:LaunchProgram,psyrip}"; Flags: nowait postinstall skipifsilent

[Code]
const
  Exts = '.mp3 .flac .m4a .ogg .opus .wav .aif .aiff .wv .ape .wma ';

{ Deutsch im Installer gewählt und noch keine Konfiguration vorhanden → psyrip startet auf Deutsch }
procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
begin
  if (CurStep = ssPostInstall) and (ActiveLanguage = 'de') then
  begin
    Dir := ExpandConstant('{userappdata}\psyrip');
    if not FileExists(Dir + '\config.json') then
    begin
      ForceDirectories(Dir);
      SaveStringToFile(Dir + '\config.json', '{"language": "de"}', False);
    end;
  end;
end;

{ Explorer-Kontextmenü („Convert To“/„Edit ID-Tags“), das psyrip im Control Center registrieren kann, wieder entfernen }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Rest, Ext: String;
  P: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Rest := Exts;
    P := Pos(' ', Rest);
    while P > 0 do
    begin
      Ext := Copy(Rest, 1, P - 1);
      Delete(Rest, 1, P);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\SystemFileAssociations\' + Ext + '\shell\psyrip.convert');
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\SystemFileAssociations\' + Ext + '\shell\psyrip.tags');
      P := Pos(' ', Rest);
    end;
  end;
end;
