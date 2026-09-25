Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error @"
.venv not found. Create it from the repo root, then install dependencies:

  python -m venv .venv
  .\.venv\Scripts\pip install -e ".[dev]"

"@
}

Write-Host "Installing package and PyInstaller..."
& $python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$icon = Join-Path $PWD "web\app-icon.ico"
if (-not (Test-Path $icon)) {
    Write-Error "Missing web\app-icon.ico"
}

Write-Host "Building application with PyInstaller..."
& $python -m PyInstaller --noconfirm (Join-Path $PWD "PDReader.spec")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = Join-Path $PWD "dist\PDReader\PDReader.exe"
if (-not (Test-Path $exe)) {
    Write-Error "PyInstaller did not create $exe"
}

$payload = Join-Path $PWD "build\installer-payload"
if (Test-Path $payload) {
    Remove-Item -Recurse -Force $payload
}
New-Item -ItemType Directory -Force -Path (Split-Path $payload) | Out-Null
Copy-Item -Recurse (Join-Path $PWD "dist\PDReader") $payload

function Find-ISCC {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "PPTStudyBuild\InnoSetup\ISCC.exe"),
        (Join-Path $PWD "tools\InnoSetup\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    return $null
}

$iscc = Find-ISCC
if ($iscc) {
    Write-Host "Compiling Inno Setup installer with $iscc"
    & $iscc (Join-Path $PWD "scripts\PDReader.iss")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "Inno Setup not found; building bundled Setup.exe with PyInstaller..."
    & $python -m PyInstaller --noconfirm (Join-Path $PWD "PDReaderSetup.spec")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$setup = Join-Path $PWD "dist\PDReaderSetup.exe"
if (-not (Test-Path $setup)) {
    Write-Error "Installer was not created at $setup"
}

Write-Host "Installer ready: $setup"
Write-Host "Copy this file to another Windows PC and double-click to install."
