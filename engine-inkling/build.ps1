# engine-inkling/build.ps1 - build AryaInfer's Inkling 2 Mini engine (strata-inkling) from the
# vendored Strata source under engine-inkling\src, for the card this host has (sm_89 on the Ada
# desktop host, sm_120 on the Blackwell laptop; -Arch overrides).
#
# The engine is upstream Strata's Inkling shape engine (MIT, Niko1221/Strata) built here instead of
# downloaded, so the Inkling 2 Mini model runs on the release this fork actually ships.  See
# docs/INKLING.md for what changes between releases and how the numbers were measured.
#
#   powershell -ExecutionPolicy Bypass -File engine-inkling\build.ps1
#   ... -Reconfigure     configure again (after a source or CMake change)
#   ... -Parallel 12     fewer compile jobs (default: 20)
#   ... -Arch 120        compile for one architecture (default: this card's compute capability)
#   ... -Cuda <toolkit>  a CUDA toolkit with bin\nvcc.exe (default: the desktop host's copy, then
#                        the newest one under C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA)
#
# Outputs (all gitignored except this file):
#   engine-inkling\strata-inkling.exe   the engine the server runs
#   engine-inkling\BUILD.json           what the Engines view and setup.py read
#   engine-inkling\build.log            the whole build's output

param(
    [string]$Work = "",
    [string]$Cuda = "C:\AI\Strata-data\cuda\13.1.2",
    [string]$Vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    [string]$Arch = "",
    [int]$Parallel = 20,
    [switch]$Reconfigure
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $root 'src\engine'
$log = Join-Path $root 'build.log'
$exe = Join-Path $root 'strata-inkling.exe'

if (-not (Test-Path (Join-Path $src 'CMakeLists.txt'))) {
    throw "no engine source at $src - unpack Strata-main so that engine\CMakeLists.txt sits there"
}
if (-not $Work) { $Work = Join-Path $root 'build' }
if (-not (Test-Path (Join-Path $Cuda 'bin\nvcc.exe'))) {
    # A host that installed the toolkit the usual way keeps nvcc under
    # C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.x, not under the CUDA folder the
    # desktop host keeps in its data directory; take the newest toolkit that has it.
    $kit = Get-ChildItem 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA' -Directory -ErrorAction SilentlyContinue |
          Where-Object { Test-Path (Join-Path $_.FullName 'bin\nvcc.exe') } |
          Sort-Object Name -Descending | Select-Object -First 1
    if ($kit) { $Cuda = $kit.FullName }
}
if (-not (Test-Path (Join-Path $Cuda 'bin\nvcc.exe'))) {
    throw "no nvcc at $Cuda\bin\nvcc.exe - pass -Cuda <toolkit>"
}

# The card this host has, unless one was asked for.  sm_89 is what the desktop host's Ada card
# compiles for, so an empty answer there is the same build as before; a Blackwell card (compute
# capability 12.0) needs sm_120 or the cubins will not load.
if (-not $Arch) {
    $cap = ''
    try {
        $cap = (cmd.exe /c 'nvidia-smi --query-gpu=compute_cap --format=csv,noheader' 2>$null |
                Select-Object -First 1).Trim() -replace '\.', ''
    } catch { }
    $Arch = if ($cap -match '^\d+$') { $cap } else { '89' }
}

# The toolkit version, read from nvcc rather than assumed, so BUILD.json records what compiled it.
$release = ''
try {
    $v = & "$Cuda\bin\nvcc.exe" --version 2>$null | Select-String -Pattern 'release\s+([0-9]+\.[0-9]+)' -List
    if ($v) { $release = $v.Matches[0].Groups[1].Value }
} catch { }

# The project version, read from the source rather than kept in a second place.
$version = '0.0.0'
$m = Select-String -Path (Join-Path $src 'CMakeLists.txt') -Pattern 'project\s*\(\s*strata\s+VERSION\s+([0-9][0-9.]*)' -List
if ($m) { $version = $m.Matches[0].Groups[1].Value }

# cmake and ninja: the Python the host already has (the CUDA kit does not ship them).
$tools = @()
foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python313\Scripts",
                 "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
                 "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
                 'C:\Program Files\CMake\bin')) {
    if (Test-Path (Join-Path $p 'cmake.exe')) { $tools += $p }
}
foreach ($p in @('C:\Program Files\CMake\bin', 'C:\Program Files\Ninja')) {
    if ((Test-Path (Join-Path $p 'ninja.exe')) -and ($tools -notcontains $p)) { $tools += $p }
}
if (-not ($tools | Where-Object { Test-Path (Join-Path $_ 'ninja.exe') })) {
    # ninja installed somewhere else on PATH (a WinGet link, the Python 'ninja' package).
    $n = Get-Command ninja.exe -ErrorAction SilentlyContinue
    if ($n) { $tools += (Split-Path -Parent $n.Source) }
}
if (-not ($tools | Where-Object { Test-Path (Join-Path $_ 'cmake.exe') })) {
    throw "cmake.exe not found - install CMake or the Python 'cmake' package"
}

$cmd = New-Object System.Collections.Generic.List[string]
$cmd.Add('@echo off')
$cmd.Add('setlocal')
$cmd.Add("call `"$Vcvars`" >nul || exit /b 1")
$cmd.Add("set `"PATH=$Cuda\bin;$(($tools -join ';'));%PATH%`"")
$configure = @(
    'cmake', '-S', "`"$src`"", '-B', "`"$Work`"", '-G', 'Ninja',
    '-DCMAKE_BUILD_TYPE=Release',
    '-DSTRATA_ENABLE_CUDA=ON',
    "-DCMAKE_CUDA_ARCHITECTURES=$Arch",
    "-DCMAKE_CUDA_COMPILER=`"$Cuda\bin\nvcc.exe`"",
    '-DSTRATA_BUILD_INKLING=ON',
    '-DSTRATA_BUILD_INKLING2=ON',
    '-DSTRATA_BUILD_TESTS=OFF'
) -join ' '
$cmd.Add("if not exist `"$Work\build.ninja`" ( $configure ) || exit /b 1")
if ($Reconfigure) { $cmd.Add("$configure || exit /b 1") }
$cmd.Add("cmake --build `"$Work`" --target strata-inkling --parallel $Parallel || exit /b 1")
$cmd.Add('exit /b 0')

$bat = Join-Path $env:TEMP "inkling-build-$PID.cmd"
Set-Content -Path $bat -Value ($cmd -join "`r`n") -Encoding ascii

try {
    Write-Host "building strata-inkling $version (sm_$Arch) - log: $log"
    # stdin comes from NUL: a build started by a detached process (a scheduled task, a background job)
    # otherwise inherits an idle pipe and a compiler probe that reads stdin waits on it forever.
    cmd.exe /c "`"$bat`" > `"$log`" 2>&1 < NUL"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "build failed (exit $LASTEXITCODE) - the last lines of $log`:"
        Get-Content $log -Tail 40 | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
} finally {
    Remove-Item $bat -ErrorAction SilentlyContinue
}

# The build writes build\engine\strata-inkling.exe (or build\strata-inkling.exe, by generator).
$made = Get-ChildItem -Path $Work -Filter 'strata-inkling.exe' -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $made) { throw "the build finished but no strata-inkling.exe is under $Work" }
Copy-Item $made.FullName $exe -Force

# The runtime DLLs the release archive also ships: cuBLAS (the engine links it) and the CUDA runtime
# when it is the shared one.  cuBLAS lives under the toolkit's bin\x64; the runtime sits in bin.
$deps = @('cublas64_13.dll', 'cublasLt64_13.dll', 'cudart64_13.dll')
$copied = @()
foreach ($dll in $deps) {
    $from = Join-Path $Cuda "bin\x64\$dll"
    if (-not (Test-Path $from)) { $from = Join-Path $Cuda "bin\$dll" }
    if (Test-Path $from) { Copy-Item $from (Join-Path $root $dll) -Force; $copied += $dll }
}
# OpenMP and the MSVC runtime: taken from the VC redist when present (the server's DLL folders also carry them).
foreach ($dll in @('VCOMP140.DLL', 'MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')) {
    if (Test-Path (Join-Path $root $dll)) { continue }
    $from = Join-Path $env:WINDIR "System32\$dll"
    if (Test-Path $from) { Copy-Item $from (Join-Path $root $dll) -Force; $copied += $dll }
}

# The engine version, not the fork lane's: setup.py and serve/engines.py compare this against
# engines.json's min_version, so writing "0.1.0" here would report the engine as older than the pin.
$build = [ordered]@{
    version      = $version
    shape        = 'inkling2'
    source       = 'vendored'
    core         = 'Niko1221/Strata'
    core_version = $version
    archs        = @([int]$Arch)
    cuda         = if ($release -match '^(\d+)') { "$($Matches[1]).0" } else { '13.1' }
    cuda_toolkit = if ($release) { $release } else { '13.1.2' }
    built        = (Get-Date).ToString('yyyy-MM-dd')
}
($build | ConvertTo-Json -Depth 4) | Set-Content -Path (Join-Path $root 'BUILD.json') -Encoding utf8

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "ok: $exe ($size MB) from Strata $version, archs $Arch"
if ($copied) { Write-Host "    runtime: $($copied -join ', ')" }
Write-Host "    next: point a run config's exe at it (strata-inkling-2-mini-sq15-0168.json)"