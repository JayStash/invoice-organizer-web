param(
    [string]$InnoCompiler
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $projectRoot
$distRoot = Join-Path $workspaceRoot "dist"
$appName = ([char[]](0x53D1, 0x7968, 0x6574, 0x7406, 0x5DE5, 0x5177)) -join ""
$releaseDir = Join-Path $distRoot $appName
$releaseExe = Join-Path $releaseDir "$appName.exe"
$scriptPath = Join-Path $projectRoot "installer\invoice-organizer.iss"
$outputPath = Join-Path $distRoot "installer\$appName-Setup.exe"

if (-not (Test-Path -LiteralPath $releaseExe -PathType Leaf)) {
    throw "Release executable not found: $releaseExe. Run .\build.ps1 first."
}

if (-not $InnoCompiler) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $InnoCompiler = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
}

if (-not $InnoCompiler) {
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        $InnoCompiler = $command.Source
    }
}

if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup 6 compiler ISCC.exe was not found."
}

New-Item -ItemType Directory -Path (Split-Path -Parent $outputPath) -Force | Out-Null

Push-Location (Split-Path -Parent $scriptPath)
try {
    & $InnoCompiler $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw "Installer output was not found: $outputPath"
}

$size = (Get-Item -LiteralPath $outputPath).Length
Write-Host "Installer build complete: $outputPath"
Write-Host ("Installer size: {0:N2} MB" -f ($size / 1MB))
