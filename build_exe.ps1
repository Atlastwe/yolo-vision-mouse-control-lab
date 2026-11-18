param(
    [string]$Python = "python",
    [string]$ModelPath = "",
    [string]$IbInputDllPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist\YoloVisionControl"

Push-Location $ProjectRoot
try {
    $RunningExecutable = Get-Process -Name "YoloVisionControl" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq (Join-Path $DistRoot "YoloVisionControl.exe") }
    if ($RunningExecutable) {
        throw "YoloVisionControl.exe is running. Close the desktop app before rebuilding."
    }

    $ProjectRootFull = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $DistRootFull = [IO.Path]::GetFullPath($DistRoot)
    if (-not $DistRootFull.StartsWith("$ProjectRootFull\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a distribution path outside the project: $DistRootFull"
    }
    if (Test-Path -LiteralPath $DistRootFull) {
        for ($Attempt = 1; $Attempt -le 5; $Attempt++) {
            try {
                Remove-Item -LiteralPath $DistRootFull -Recurse -Force -ErrorAction Stop
                break
            }
            catch {
                if ($Attempt -eq 5) {
                    throw "Unable to clean $DistRootFull. Close the app or any Explorer preview using it."
                }
                Start-Sleep -Seconds 1
            }
        }
    }

    & $Python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed. EXE build was not started."
    }

    # This Conda environment contains two Intel OpenMP DLLs. PyInstaller's
    # isolated torch scanner imports torch before numpy, unlike the app.
    # Limit the compatibility override to build-time analysis only.
    $PreviousKmpDuplicateLibOk = $env:KMP_DUPLICATE_LIB_OK
    try {
        $env:KMP_DUPLICATE_LIB_OK = "TRUE"
        & $Python -m PyInstaller --noconfirm --clean YoloVisionControl.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        $env:KMP_DUPLICATE_LIB_OK = $PreviousKmpDuplicateLibOk
    }

    $PythonPrefix = (& $Python -c "import sys; print(sys.prefix)").Trim()
    $CondaBin = Join-Path $PythonPrefix "Library\bin"
    $InternalDirectory = Join-Path $DistRoot "_internal"
    if (Test-Path -LiteralPath $CondaBin) {
        foreach ($Pattern in @("mkl_*.dll", "libiomp5md.dll", "libiompstubs5md.dll", "tbb*.dll")) {
            Get-ChildItem -LiteralPath $CondaBin -Filter $Pattern -File -ErrorAction SilentlyContinue |
                Copy-Item -Destination $InternalDirectory -Force
        }
    }

    $ModelsDirectory = Join-Path $DistRoot "models"
    New-Item -ItemType Directory -Force -Path $ModelsDirectory | Out-Null

    if ($ModelPath) {
        $ResolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
        Copy-Item -LiteralPath $ResolvedModel -Destination (Join-Path $ModelsDirectory "best.engine") -Force
    }

    if ($IbInputDllPath) {
        $ResolvedIbInputDll = (Resolve-Path -LiteralPath $IbInputDllPath).Path
        $IbInputDirectory = Join-Path $DistRoot "IbInputSimulator-0.4.1\Binding.AHK2"
        New-Item -ItemType Directory -Force -Path $IbInputDirectory | Out-Null
        Copy-Item -LiteralPath $ResolvedIbInputDll -Destination (Join-Path $IbInputDirectory "IbInputSimulator.dll") -Force
    }

    Write-Host "Build completed: $DistRoot"
    Write-Host "Launch with: .\dist\YoloVisionControl\YoloVisionControl.exe"
}
finally {
    Pop-Location
}
