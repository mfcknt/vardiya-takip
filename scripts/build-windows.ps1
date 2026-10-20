param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
function Run-Step {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Islem basarisiz: $Program" }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Run-Step "py" @("-3.12", "-m", "venv", ".venv")
}
$ProjectPython = Join-Path $PWD ".venv\Scripts\python.exe"
Run-Step $ProjectPython @("-m", "pip", "install", "-e", ".[test,build]")
if (-not $SkipTests) { Run-Step $ProjectPython @("-m", "pytest", "-q") }
Run-Step $ProjectPython @("-m", "PyInstaller", "--noconfirm", "--clean", "VardiyaTakip.spec")
Copy-Item "README.md" "dist\VardiyaTakip\README.md"
Copy-Item "docs" "dist\VardiyaTakip\docs" -Recurse -Force
Run-Step $ProjectPython @("scripts\collect_licenses.py", "dist\VardiyaTakip\THIRD_PARTY")
$archive = "dist\VardiyaTakip-Windows-x64.zip"
if (Test-Path $archive) { Remove-Item $archive }
Compress-Archive -Path "dist\VardiyaTakip" -DestinationPath $archive
Write-Host "Hazir: $archive"
