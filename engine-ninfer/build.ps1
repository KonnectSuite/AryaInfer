# Builds the pinned NInfer engine plus AryaInfer's line-protocol shim.
#
# Inputs: the pinned roofkid/ninfer-4080 source, the AryaInfer patch, NVIDIA NVTX
# v3.1.0 headers (CUDA 13 no longer ships them), vcpkg packages (ffmpeg, curl),
# Visual Studio 2022 and CUDA 13.1.
#
# Usage (from a normal prompt):
#   powershell -ExecutionPolicy Bypass -File engine-ninfer\build.ps1
# or run engine-ninfer\build.cmd, which does the same.

param(
    [string]$Work = (Join-Path $PSScriptRoot '..\build-ninfer'),
    [string]$Vcpkg = 'C:\vcpkg',
    [string]$Cuda = 'C:\AI\Strata-data\cuda\13.1.2',
    [string]$Vcvars = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Work = [IO.Path]::GetFullPath($Work)
$Src = Join-Path $Work 'src'
$Build = Join-Path $Work 'build'
$Commit = '2469b5752672ad597055af61fe28e8e7ced20056'
$TarSha = '4DBDC09000E0358DF70A4DBDD824EDC1CB853FA48634A4877554D7F1841379BA'
$Tar = Join-Path $Work 'ninfer-src.tar.gz'
$Patch = Join-Path $PSScriptRoot 'patches\0001-ninfer-windows.patch'

function Step($text) { Write-Host "== $text" }

Step "source $Commit"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
if (-not (Test-Path $Tar)) {
    curl.exe -L --fail --retry 5 --retry-delay 3 -o $Tar "https://codeload.github.com/roofkid/ninfer-4080/tar.gz/$Commit"
}
$hash = (Get-FileHash $Tar -Algorithm SHA256).Hash
if ($hash -ne $TarSha) { throw "source tarball hash $hash does not match $TarSha" }
if (-not (Test-Path $Src)) {
    $tmp = Join-Path $Work 'extract'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    tar.exe -xzf $Tar -C $tmp
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    Move-Item $inner.FullName $Src
    Remove-Item $tmp -Recurse -Force
    git -C $Src init -q
    git -C $Src apply --whitespace=nowarn $Patch
  Step "patch applied"
}

Step 'NVTX v3.1.0 headers (CUDA 13 does not ship them)'
$NvtxDir = Join-Path $Src 'include\nvtx3'
if (-not (Test-Path $NvtxDir)) {
    $nvtxTar = Join-Path $Work 'nvtx-v3.1.0.tar.gz'
    if (-not (Test-Path $nvtxTar)) {
        curl.exe -L --fail -o $nvtxTar 'https://github.com/NVIDIA/NVTX/archive/refs/tags/v3.1.0.tar.gz'
    }
    $nvtxTmp = Join-Path $Work 'nvtx-extract'
    if (Test-Path $nvtxTmp) { Remove-Item $nvtxTmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $nvtxTmp | Out-Null
    tar.exe -xzf $nvtxTar -C $nvtxTmp
    $root = Get-ChildItem $nvtxTmp -Directory | Select-Object -First 1
    Copy-Item (Join-Path $root.FullName 'c\include\nvtx3') $NvtxDir -Recurse
    Remove-Item $nvtxTmp -Recurse -Force
}

Step "vcpkg at $Vcpkg"
if (-not (Test-Path (Join-Path $Vcpkg 'vcpkg.exe'))) {
    if (-not (Test-Path (Join-Path $Vcpkg '.git'))) {
        git clone --depth 1 https://github.com/microsoft/vcpkg $Vcpkg
    }
    git -C $Vcpkg fetch --depth 1 origin 4bca8fd8654e5ba76f92661db7bfe954768ad8ef
    cmd.exe /c "call `"$Vcpkg\bootstrap-vcpkg.bat`" -disableMetrics" | Out-Null
}

Step 'vcpkg packages'
cmd.exe /c "cd /d `"$Src`" && `"$Vcpkg\vcpkg.exe`" install --triplet x64-windows"
if ($LASTEXITCODE -ne 0) { throw 'vcpkg install failed' }

Step 'cmake configure and build'
$shim = (Join-Path $PSScriptRoot 'shim\main.cpp') -replace '\\', '/'
$bat = Join-Path $Work 'build-engine.cmd'
$cmake = "cmake -S `"$Src`" -B `"$Build`" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89 -DCMAKE_CUDA_COMPILER=`"$Cuda\bin\nvcc.exe`" -DNINFER_BUILD_APPS=ON -DNINFER_BUILD_BENCHMARKS=ON -DNINFER_ARYAINFER_SHIM=`"$shim`" -DCMAKE_CXX_FLAGS=/utf-8 -DCMAKE_TOOLCHAIN_FILE=`"$Vcpkg\scripts\buildsystems\vcpkg.cmake`" -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_MANIFEST_DIR=`"$Src`" -DVCPKG_INSTALLED_DIR=`"$Src\vcpkg_installed`""
$lines = @(
    '@echo off',
    "call `"$Vcvars`" || exit /b 1",
    "set `"PATH=$Cuda\bin;%PATH%`"",
    $cmake,
    'if errorlevel 1 exit /b 1',
    "cmake --build `"$Build`" --target ninfer-engine --parallel 20"
)
Set-Content -Path $bat -Value $lines -Encoding ascii
$log = Join-Path $Work 'build.log'
cmd.exe /c "`"$bat`" > `"$log`" 2>&1"
if ($LASTEXITCODE -ne 0) { throw "build failed; see $log" }

Copy-Item (Join-Path $Build 'apps\ninfer-engine.exe') (Join-Path $PSScriptRoot 'ninfer-engine.exe') -Force
Step "done: $(Join-Path $PSScriptRoot 'ninfer-engine.exe')"
