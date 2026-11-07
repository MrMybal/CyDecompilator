param([string]$OutputDirectory = '', [string]$BuildDirectory = '')
$ErrorActionPreference = 'Stop'
# Builds the Windows launcher. The executable only starts the private interpreter on
# app/desktop.py: it embeds no Python and no model, so rebuilding it never touches data/.
# MSVC is located through vswhere rather than assumed to be on PATH, because the developer
# shell that has `cl` is not the shell this script is usually run from.
$appRoot = $PSScriptRoot
$toolRoot = Split-Path -Parent $appRoot
$build = if ($BuildDirectory) { $BuildDirectory } else { Join-Path $toolRoot 'runtime/build/launchers' }
New-Item -ItemType Directory -Force -Path $build | Out-Null

function Get-VcVars {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path $vswhere)) {
        throw 'vswhere.exe was not found. Install the Visual Studio C++ build tools.'
    }
    $install = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $install) {
        throw 'No Visual Studio installation with the C++ build tools was found.'
    }
    $vcvars = Join-Path $install 'VC/Auxiliary/Build/vcvars64.bat'
    if (-not (Test-Path $vcvars)) { throw "vcvars64.bat was not found under $install" }
    return $vcvars
}

$destination = if ($OutputDirectory) { $OutputDirectory } else { $toolRoot }
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$source = Join-Path $appRoot 'launcher.cpp'
$resources = Join-Path $appRoot 'launcher.rc'
$compiled = Join-Path $build 'launcher.res'

foreach ($variant in @(
    @{ Name='CyDecompilator.exe'; Define=''; Subsystem='WINDOWS' },
    @{ Name='CyDecompilatorCLI.exe'; Define='/DCYDEC_CLI'; Subsystem='CONSOLE' },
    @{ Name='python-proxy.exe'; Define='/DCYDEC_PYTHON_PROXY'; Subsystem='CONSOLE' }
)) {
$output = Join-Path $destination $variant.Name
if (Get-Command cl -ErrorAction SilentlyContinue) {
    Push-Location $build
    try {
        & rc /nologo /i $appRoot /fo $compiled $resources
        if ($LASTEXITCODE -ne 0) { throw 'Resource compilation failed' }
        $compilerOptions = @('/nologo','/std:c++17','/MT','/EHsc','/O2','/Brepro','/experimental:deterministic','/pathmap:' + $toolRoot + '=src')
        if ($variant.Define) { $compilerOptions += $variant.Define }
        & cl @compilerOptions $source $compiled "/Fe:$output" /link ("/SUBSYSTEM:" + $variant.Subsystem) user32.lib
        if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed' }
    } finally { Pop-Location }
} else {
    $vcvars = Get-VcVars
    $quote = [char]34
    $line = 'call ' + $quote + $vcvars + $quote + ' >nul && cd /d ' + $quote + $build + $quote +
            ' && rc /nologo /i ' + $quote + $appRoot + $quote + ' /fo ' + $quote + $compiled + $quote + ' ' +
            $quote + $resources + $quote +
            ' && cl /nologo /std:c++17 /MT /EHsc /O2 /Brepro /experimental:deterministic ' + $variant.Define +
            ' /pathmap:' + $quote + $toolRoot + '=src' + $quote + ' ' + $quote + $source + $quote + ' ' + $quote + $compiled + $quote +
            ' /Fe:' + $quote + $output + $quote + ' /link /SUBSYSTEM:' + $variant.Subsystem + ' user32.lib'
    & cmd.exe /c $line
    if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed' }
}

if (-not (Test-Path $output)) { throw "The launcher was not produced at $output" }
Write-Host ("Built {0} ({1} bytes)" -f $output, (Get-Item $output).Length)
}
