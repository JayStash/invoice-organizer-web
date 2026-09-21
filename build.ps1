param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $projectRoot
$distRoot = Join-Path $workspaceRoot "dist"
$specPath = Join-Path $projectRoot "invoice-organizer.spec"

Push-Location $projectRoot
try {
    & $Python -m pip install -r (Join-Path $projectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }

    & $Python -m PyInstaller --noconfirm --clean --distpath $distRoot $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    Write-Host "Build complete: $distRoot\发票整理工具\发票整理工具.exe"
}
finally {
    Pop-Location
}
