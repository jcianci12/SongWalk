param(
  [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$SpecFile = Join-Path $RepoRoot "build\pyinstaller\SongWalk.spec"
$BuildRoot = if ($OutputRoot) {
  $OutputRoot
} else {
  Join-Path $RepoRoot "build\pyinstaller"
}
$DistPath = Join-Path $BuildRoot "dist\windows"
$WorkPath = Join-Path $BuildRoot "build\windows"

function Invoke-Python {
  param([string[]]$Arguments)
  & $VenvPython @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: $($Arguments -join ' ')"
  }
}

if (-not (Test-Path $VenvPython)) {
  python -m venv (Join-Path $RepoRoot ".venv")
}

Invoke-Python @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python @("-m", "pip", "install", "-r", (Join-Path $RepoRoot "requirements.txt"), "-r", (Join-Path $RepoRoot "build\pyinstaller\requirements.txt"))

New-Item -ItemType Directory -Force -Path $DistPath | Out-Null
New-Item -ItemType Directory -Force -Path $WorkPath | Out-Null

Invoke-Python @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--distpath", $DistPath,
  "--workpath", $WorkPath,
  $SpecFile
)

Write-Host ""
Write-Host "Build complete."
Write-Host ("Executable folder: " + (Join-Path $DistPath "SongWalk"))
Write-Host ("Run: " + (Join-Path $DistPath "SongWalk\SongWalk.exe"))
