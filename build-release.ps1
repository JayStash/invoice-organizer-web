param(
    [string]$Python = "python",
    [string]$InnoCompiler
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $projectRoot
$distRoot = Join-Path $workspaceRoot "dist"
$versionPath = Join-Path $projectRoot "VERSION"
$version = (Get-Content -LiteralPath $versionPath -Raw).Trim()

if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION must contain a numeric MAJOR.MINOR.PATCH version."
}

$appName = ([char[]](0x53D1, 0x7968, 0x6574, 0x7406, 0x5DE5, 0x5177)) -join ""
$releaseDir = Join-Path $distRoot $appName
$setupPath = Join-Path $distRoot "installer\$appName-Setup.exe"
$archiveDir = Join-Path $distRoot "releases\v$version"
$portableArchive = Join-Path $archiveDir "$appName-Windows-x64-v$version.zip"
$setupArchive = Join-Path $archiveDir "$appName-Setup-v$version.exe"

if ((Test-Path -LiteralPath $portableArchive) -or (Test-Path -LiteralPath $setupArchive)) {
    throw "Release v$version already exists and will not be overwritten: $archiveDir"
}

& (Join-Path $projectRoot "build.ps1") -Python $Python
if ($LASTEXITCODE -ne 0) {
    throw "Portable build failed with exit code $LASTEXITCODE."
}

$installerArgs = @{}
if ($InnoCompiler) {
    $installerArgs["InnoCompiler"] = $InnoCompiler
}
& (Join-Path $projectRoot "build-installer.ps1") @installerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $releaseDir -PathType Container)) {
    throw "Portable release directory was not found: $releaseDir"
}
if (-not (Test-Path -LiteralPath $setupPath -PathType Leaf)) {
    throw "Setup executable was not found: $setupPath"
}

New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
Compress-Archive -LiteralPath $releaseDir -DestinationPath $portableArchive -CompressionLevel Optimal
Copy-Item -LiteralPath $setupPath -Destination $setupArchive

Write-Host "Release archive complete: $archiveDir"
Write-Host "Portable: $portableArchive"
Write-Host "Setup: $setupArchive"
