param(
    [string]$Version = "0.1.0",
    [string]$SevenZip = "C:\Program Files\7-Zip\7z.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist\YoloVisionControl"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$ArchiveName = "YoloVisionControl-v$Version-windows-x64.7z"
$ArchivePath = Join-Path $ReleaseRoot $ArchiveName
$ChecksumPath = "$ArchivePath.sha256"
$GitHubAssetLimit = 2GB

if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) {
    throw "7-Zip was not found: $SevenZip"
}
if (-not (Test-Path -LiteralPath (Join-Path $DistRoot "YoloVisionControl.exe") -PathType Leaf)) {
    throw "Build output was not found. Run build_exe.ps1 first."
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
Remove-Item -LiteralPath $ArchivePath, $ChecksumPath -Force -ErrorAction SilentlyContinue

Push-Location (Join-Path $ProjectRoot "dist")
try {
    & $SevenZip a -t7z -mx=7 -m0=lzma2 -mmt=on $ArchivePath "YoloVisionControl"
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$Archive = Get-Item -LiteralPath $ArchivePath
if ($Archive.Length -ge $GitHubAssetLimit) {
    throw "Archive is $($Archive.Length) bytes, which exceeds GitHub's 2 GiB asset limit."
}

$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $ChecksumPath -Value "$Hash  $ArchiveName" -Encoding ascii

Write-Host "Release package: $ArchivePath"
Write-Host "Archive size: $([math]::Round($Archive.Length / 1GB, 2)) GiB"
Write-Host "SHA-256: $Hash"
