[CmdletBinding()]
param(
    [switch]$SkipInno
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $root
$spec = Join-Path $PSScriptRoot 'VideoLibrary.spec'
$dist = Join-Path $root 'dist'
$work = Join-Path $root 'pyinstaller-work'
$output = Join-Path $root 'output'

Write-Host '=== VideoLibrary Windows build ==='
Write-Host "Repository: $repo"

python -m pip install --disable-pip-version-check 'pyinstaller>=6.0,<7.0'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }

if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $output | Out-Null

python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$exe = Join-Path $dist 'VideoLibrary\VideoLibrary.exe'
if (-not (Test-Path $exe)) { throw "Executable not found: $exe" }
Write-Host "PyInstaller OK: $exe"

if ($SkipInno) {
    Write-Host 'Inno Setup skipped.'
    exit 0
}

$iscc = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $iscc) {
    $isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($isccCommand) { $iscc = $isccCommand.Source }
}
if (-not $iscc) {
    throw 'Inno Setup 6 (ISCC.exe) was not found.'
}

$iss = Join-Path $root 'installer\VideoLibrary.iss'
Write-Host "Inno Setup: $iscc"
& $iscc $iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }

$setup = Get-ChildItem -Path $output -Filter 'VideoLibrary-*-setup.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw 'Installer was not generated.' }
Write-Host "Installer OK: $($setup.FullName)"
