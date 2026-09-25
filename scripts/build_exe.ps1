Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error @"
.venv not found. Create it from the repo root, then install dev dependencies:

  python -m venv .venv
  .\.venv\Scripts\pip install -e ".[dev]"

"@
    exit 1
}

& $python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m PyInstaller --noconfirm (Join-Path $PWD "PDReader.spec")

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
