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
$englishSetupName = "invoice-organizer-Setup-v$version.exe"
$releaseNames = [ordered]@{
    LocalPortable = "$appName-Windows-x64-v$version.zip"
    LocalSetup = "$appName-Setup-v$version.exe"
    GitHubPortable = "invoice-organizer-Windows-x64-v$version.zip"
    GitHubSetup = $englishSetupName
    GitHubPortableLabel = "$appName v$version 便携版"
    GitHubSetupLabel = "$appName v$version 安装版"
    ServerSetup = $englishSetupName
}
$releaseDir = Join-Path $distRoot $appName
$setupPath = Join-Path $distRoot "installer\$appName-Setup.exe"
$archiveDir = Join-Path $distRoot "releases\v$version"
$publishDir = Join-Path $distRoot "publish\v$version"
$portableArchive = Join-Path $archiveDir $releaseNames.LocalPortable
$setupArchive = Join-Path $archiveDir $releaseNames.LocalSetup
$githubPortable = Join-Path $publishDir $releaseNames.GitHubPortable
$githubSetup = Join-Path $publishDir $releaseNames.GitHubSetup

if (
    (Test-Path -LiteralPath $portableArchive) -or
    (Test-Path -LiteralPath $setupArchive) -or
    (Test-Path -LiteralPath $githubPortable) -or
    (Test-Path -LiteralPath $githubSetup)
) {
    throw "Release or publishing files for v$version already exist and will not be overwritten."
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
New-Item -ItemType Directory -Path $publishDir -Force | Out-Null
Copy-Item -LiteralPath $portableArchive -Destination $githubPortable
Copy-Item -LiteralPath $setupArchive -Destination $githubSetup

Write-Host "Release archive complete: $archiveDir"
Write-Host "Portable: $portableArchive"
Write-Host "Setup: $setupArchive"
Write-Host ""
Write-Host "Publishing names derived from VERSION:"
Write-Host "Publishing directory: $publishDir"
Write-Host "GitHub portable file: $githubPortable"
Write-Host "GitHub portable label: $($releaseNames.GitHubPortableLabel)"
Write-Host "GitHub Setup file: $githubSetup"
Write-Host "GitHub Setup label: $($releaseNames.GitHubSetupLabel)"
Write-Host "Update server Setup filename: $($releaseNames.ServerSetup)"
