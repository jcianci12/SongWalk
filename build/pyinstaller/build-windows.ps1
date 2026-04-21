param(
  [string]$OutputRoot = "",
  [switch]$SkipDependencyInstall,
  [switch]$RefreshCloudflared,
  [switch]$SkipPackagedProcessShutdown
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
$CloudflaredCache = Join-Path $RepoRoot "build\pyinstaller\vendor\cloudflared-windows-amd64.exe"
$ExeFolder = Join-Path $DistPath "SongWalk"
$SongWalkExe = Join-Path $ExeFolder "SongWalk.exe"
$CloudflaredExe = Join-Path $ExeFolder "cloudflared.exe"

function ConvertTo-NormalizedFullPath {
  param([string]$Path)

  return [System.IO.Path]::GetFullPath($Path).TrimEnd("\")
}

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

function Stop-PackagedExecutableProcess {
  param(
    [string]$ProcessName,
    [string]$TargetExePath
  )

  $normalizedTarget = ConvertTo-NormalizedFullPath -Path $TargetExePath
  $targetDirectory = Split-Path -Path $normalizedTarget -Parent

  $matchingProcesses = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and (ConvertTo-NormalizedFullPath -Path $_.Path) -ieq $normalizedTarget
  }

  if (-not $matchingProcesses) {
    return
  }

  $matchingProcessCount = @($matchingProcesses).Count
  $pluralSuffix = if ($matchingProcessCount -gt 1) { "es" } else { "" }
  Write-Host ("Stopping packaged {0}.exe process{1} from {2}..." -f $ProcessName, $pluralSuffix, $targetDirectory)

  foreach ($process in $matchingProcesses) {
    Write-Host ("  PID {0}: {1}" -f $process.Id, $process.Path)
    Stop-Process -Id $process.Id -Force -ErrorAction Stop
  }

  Start-Sleep -Milliseconds 500

  $stillRunning = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and (ConvertTo-NormalizedFullPath -Path $_.Path) -ieq $normalizedTarget
  }

  if ($stillRunning) {
    $pids = ($stillRunning | ForEach-Object { $_.Id }) -join ", "
    throw "Unable to stop packaged $ProcessName.exe process(es) from $targetDirectory. Remaining PID(s): $pids"
  }
}

function Stop-PackagedRuntimeProcesses {
  Stop-PackagedExecutableProcess -ProcessName "SongWalk" -TargetExePath $SongWalkExe
  Stop-PackagedExecutableProcess -ProcessName "cloudflared" -TargetExePath $CloudflaredExe
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

if (-not $SkipDependencyInstall) {
  Invoke-Python @("-m", "pip", "install", "--upgrade", "pip")
  Invoke-Python @("-m", "pip", "install", "-r", (Join-Path $RepoRoot "requirements.txt"), "-r", (Join-Path $RepoRoot "build\pyinstaller\requirements.txt"))
} else {
  Write-Host "Skipping dependency install."
}

New-Item -ItemType Directory -Force -Path $DistPath | Out-Null
New-Item -ItemType Directory -Force -Path $WorkPath | Out-Null
if (-not $SkipPackagedProcessShutdown) {
  Stop-PackagedRuntimeProcesses
} else {
  Write-Host "Skipping packaged runtime process shutdown."
}
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
New-Item -ItemType Directory -Force -Path (Split-Path $CloudflaredCache -Parent) | Out-Null
if ($RefreshCloudflared -or -not (Test-Path $CloudflaredCache)) {
  Write-Host "Downloading cloudflared for packaged Quick Tunnel support..."
  Invoke-WebRequest -Uri $CloudflaredUrl -OutFile $CloudflaredCache
} else {
  Write-Host "Using cached cloudflared for packaged Quick Tunnel support."
}
Copy-Item -LiteralPath $CloudflaredCache -Destination $CloudflaredTarget -Force

Write-Host ""
Write-Host "Build complete."
Write-Host ("Executable folder: " + $ExeFolder)
Write-Host ("Run: " + (Join-Path $ExeFolder "SongWalk.exe"))
Write-Host ("Bundled tunnel binary: " + $CloudflaredTarget)
