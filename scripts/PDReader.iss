#define MyAppName "PDReader"
#define MyAppVersion "0.2.14"
#define MyAppPublisher "PDReader"
#define MyAppExeName "PDReader.exe"

[Setup]
AppId={{A7C4E19B-2F58-4D6A-8B31-9C0E5D7A1B24}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\PDReader
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PDReaderSetup
SetupIconFile=..\web\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=no
LZMAUseSeparateProcess=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no
CloseApplicationsFilter=PDReader.exe,PPTStudyCompanion.exe
InfoBeforeFile=..\scripts\installer-readme.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=安装 PDReader
SetupWindowTitle=安装 PDReader
StatusExtractFiles=正在解压文件，请稍候，这可能需要一两分钟，请不要关闭窗口。
ReadyLabel1=安装程序已准备好把 PDReader 装到你的电脑。下一步会复制文件，请稍候，不要强制结束。
FinishedHeadingLabel=PDReader 已安装完成
FinishedLabel=安装程序已把 PDReader 装到你的电脑。可以立刻打开使用。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "..\dist\PDReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即打开 PDReader"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function ReadTailAnsi(const FileName: String; MaxBytes: Integer): AnsiString;
var
  F: Integer;
  Size, Count: Integer;
begin
  Result := '';
  F := FileOpen(FileName, fmOpenRead or fmShareDenyNone);
  if F = -1 then
    Exit;
  try
    Size := FileSeek(F, 0, 2);
    if Size <= 0 then
      Exit;
    Count := Size;
    if Count > MaxBytes then
      Count := MaxBytes;
    FileSeek(F, Size - Count, 0);
    SetLength(Result, Count);
    FileRead(F, Result[1], Count);
  finally
    FileClose(F);
  end;
end;

function SetupPackageVersion: String;
var
  ParamVer, Tail, Marker, Line: String;
  VersionFile: String;
  P: Integer;
begin
  ParamVer := ExpandConstant('{param:APPVERSION}');
  if ParamVer <> '' then
  begin
    Result := ParamVer;
    Exit;
  end;
  VersionFile := ExpandConstant('{srcexe}') + '.version';
  if LoadStringFromFile(VersionFile, Line) then
  begin
    Line := Trim(Line);
    P := Pos(#13, Line);
    if P > 0 then
      Line := Copy(Line, 1, P - 1);
    P := Pos(#10, Line);
    if P > 0 then
      Line := Copy(Line, 1, P - 1);
    if Line <> '' then
    begin
      Result := Line;
      Exit;
    end;
  end;
  Marker := '###PDREADER_VERSION###';
  Tail := String(ReadTailAnsi(ExpandConstant('{srcexe}'), 1024));
  P := Pos(Marker, Tail);
  if P > 0 then
  begin
    Delete(Tail, 1, P + Length(Marker) - 1);
    Tail := Trim(Tail);
    P := Pos(#10, Tail);
    if P > 0 then
      Tail := Copy(Tail, 1, P - 1);
    Tail := Trim(Tail);
    if Tail <> '' then
    begin
      Result := Tail;
      Exit;
    end;
  end;
  Result := '{#MyAppVersion}';
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM PDReader.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM PPTStudyCompanion.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  NeedsRestart := False;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM PDReader.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM PPTStudyCompanion.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Ver, Data, Dir: String;
begin
  if CurStep = ssPostInstall then
  begin
    Ver := SetupPackageVersion;
    Data := '{"version":"' + Ver + '"}';
    Dir := ExpandConstant('{userappdata}\PPTStudyCompanion');
    ForceDirectories(Dir);
    SaveStringToFile(Dir + '\installed_version.json', Data, False);
    SaveStringToFile(ExpandConstant('{app}\app_version.json'), Data, False);
  end;
end;
