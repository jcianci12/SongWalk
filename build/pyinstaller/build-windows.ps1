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
$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$ExeFolder = Join-Path $DistPath "SongWalk"

function Remove-PathWithRetries {
  param(
    [string]$TargetPath,
    [int]$Attempts = 10,
    [int]$DelayMilliseconds = 250
  )

  if (-not (Test-Path $TargetPath)) {
    return
  }

  for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
      Remove-Item -LiteralPath $TargetPath -Recurse -Force
      return
    } catch {
      if ($attempt -eq $Attempts) {
        throw "Unable to remove $TargetPath. Close any running SongWalk or cloudflared process using that folder and try again."
      }
      Start-Sleep -Milliseconds $DelayMilliseconds
    }
  }
}

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
Remove-PathWithRetries -TargetPath $ExeFolder

Invoke-Python @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--distpath", $DistPath,
  "--workpath", $WorkPath,
  $SpecFile
)

$CloudflaredTarget = Join-Path $ExeFolder "cloudflared.exe"
Write-Host "Downloading cloudflared for packaged Quick Tunnel support..."
Invoke-WebRequest -Uri $CloudflaredUrl -OutFile $CloudflaredTarget

Write-Host ""
Write-Host "Build complete."
Write-Host ("Executable folder: " + $ExeFolder)
Write-Host ("Run: " + (Join-Path $ExeFolder "SongWalk.exe"))
Write-Host ("Bundled tunnel binary: " + $CloudflaredTarget)
