param(
  [switch]$NoInitialBuild,
  [switch]$InstallDependenciesEveryBuild,
  [switch]$RefreshCloudflared,
  [switch]$CheckOnly,
  [int]$DebounceSeconds = 3,
  [int]$PollSeconds = 1
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildScript = Join-Path $RepoRoot "build\pyinstaller\build-windows.ps1"
$DependencyFiles = @(
  (Join-Path $RepoRoot "requirements.txt").ToLowerInvariant(),
  (Join-Path $RepoRoot "build\pyinstaller\requirements.txt").ToLowerInvariant()
)

$WatchedPaths = @(
  (Join-Path $RepoRoot "songshare"),
  (Join-Path $RepoRoot "build\pyinstaller\launcher.py"),
  (Join-Path $RepoRoot "build\pyinstaller\SongWalk.spec"),
  (Join-Path $RepoRoot "build\pyinstaller\build-windows.ps1"),
  (Join-Path $RepoRoot "requirements.txt"),
  (Join-Path $RepoRoot "build\pyinstaller\requirements.txt")
)

$IncludedExtensions = @(
  ".css",
  ".html",
  ".ico",
  ".js",
  ".json",
  ".md",
  ".png",
  ".ps1",
  ".py",
  ".spec",
  ".svg",
  ".txt"
)

function Test-WatchedFile {
  param([System.IO.FileInfo]$File)

  $extension = $File.Extension.ToLowerInvariant()
  if ($IncludedExtensions -notcontains $extension) {
    return $false
  }

  $path = $File.FullName.ToLowerInvariant()
  if ($path.Contains("\__pycache__\") -or $path.Contains("\.pytest_cache\")) {
    return $false
  }

  return $true
}

function Get-WatchedFiles {
  $files = New-Object System.Collections.Generic.List[System.IO.FileInfo]

  foreach ($path in $WatchedPaths) {
    if (-not (Test-Path $path)) {
      continue
    }

    $item = Get-Item -LiteralPath $path
    if ($item.PSIsContainer) {
      Get-ChildItem -LiteralPath $item.FullName -Recurse -File | ForEach-Object {
        if (Test-WatchedFile -File $_) {
          $files.Add($_)
        }
      }
    } elseif (Test-WatchedFile -File $item) {
      $files.Add($item)
    }
  }

  return $files.ToArray()
}

function New-Snapshot {
  $snapshot = @{}

  foreach ($file in Get-WatchedFiles) {
    $key = $file.FullName.ToLowerInvariant()
    $snapshot[$key] = "{0}:{1}" -f $file.LastWriteTimeUtc.Ticks, $file.Length
  }

  return $snapshot
}

function Compare-Snapshots {
  param(
    [hashtable]$OldSnapshot,
    [hashtable]$NewSnapshot
  )

  $changes = New-Object System.Collections.Generic.List[string]

  foreach ($key in $NewSnapshot.Keys) {
    if (-not $OldSnapshot.ContainsKey($key) -or $OldSnapshot[$key] -ne $NewSnapshot[$key]) {
      $changes.Add($key)
    }
  }

  foreach ($key in $OldSnapshot.Keys) {
    if (-not $NewSnapshot.ContainsKey($key)) {
      $changes.Add($key)
    }
  }

  return $changes.ToArray()
}

function ConvertTo-RelativePath {
  param([string]$Path)

  $rootPrefix = $RepoRoot.TrimEnd("\") + "\"
  if ($Path.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $Path.Substring($rootPrefix.Length)
  }

  return $Path
}

function Test-DependencyChange {
  param([string[]]$ChangedPaths)

  foreach ($path in $ChangedPaths) {
    if ($DependencyFiles -contains $path.ToLowerInvariant()) {
      return $true
    }
  }

  return $false
}

function Invoke-Rebuild {
  param(
    [string]$Reason,
    [bool]$SkipDependencyInstall
  )

  $buildArgs = @()
  if ($SkipDependencyInstall) {
    $buildArgs += "-SkipDependencyInstall"
  }
  if ($RefreshCloudflared) {
    $buildArgs += "-RefreshCloudflared"
  }

  Write-Host ""
  Write-Host ("[{0}] Rebuilding Windows exe ({1})..." -f (Get-Date -Format "HH:mm:ss"), $Reason)
  try {
    & $BuildScript @buildArgs
    if ($LASTEXITCODE -ne 0) {
      throw "Build script exited with code $LASTEXITCODE."
    }
    Write-Host ("[{0}] Rebuild complete." -f (Get-Date -Format "HH:mm:ss"))
    return $true
  } catch {
    Write-Host ("[{0}] Rebuild failed: {1}" -f (Get-Date -Format "HH:mm:ss"), $_) -ForegroundColor Red
    return $false
  }
}

$snapshot = New-Snapshot
$watchedCount = $snapshot.Count
Write-Host ("Watching {0} files for packaged exe rebuilds." -f $watchedCount)
Write-Host "Press Ctrl+C to stop."

if ($CheckOnly) {
  return
}

$dependencyInstallComplete = $false
if (-not $NoInitialBuild) {
  $dependencyInstallComplete = Invoke-Rebuild -Reason "initial" -SkipDependencyInstall:$false
}

$pending = $false
$pendingDependencyInstall = $false
$lastChangeAt = $null

while ($true) {
  Start-Sleep -Seconds $PollSeconds

  $newSnapshot = New-Snapshot
  $changes = Compare-Snapshots -OldSnapshot $snapshot -NewSnapshot $newSnapshot

  if ($changes.Count -gt 0) {
    $snapshot = $newSnapshot
    $pending = $true
    $pendingDependencyInstall = $pendingDependencyInstall -or (Test-DependencyChange -ChangedPaths $changes)
    $lastChangeAt = Get-Date

    $changedNames = $changes |
      Select-Object -First 5 |
      ForEach-Object { ConvertTo-RelativePath -Path $_ }
    $suffix = ""
    if ($changes.Count -gt 5) {
      $suffix = " and $($changes.Count - 5) more"
    }
    Write-Host ("[{0}] Change detected: {1}{2}" -f (Get-Date -Format "HH:mm:ss"), ($changedNames -join ", "), $suffix)
  }

  if ($pending -and $lastChangeAt -ne $null) {
    $quietFor = ((Get-Date) - $lastChangeAt).TotalSeconds
    if ($quietFor -ge $DebounceSeconds) {
      $skipDependencies = $dependencyInstallComplete -and
        (-not $pendingDependencyInstall) -and
        (-not $InstallDependenciesEveryBuild)

      $reason = "source change"
      if ($pendingDependencyInstall) {
        $reason = "dependency change"
      }

      $success = Invoke-Rebuild -Reason $reason -SkipDependencyInstall:$skipDependencies
      if ($success -and -not $skipDependencies) {
        $dependencyInstallComplete = $true
      }

      $pending = $false
      $pendingDependencyInstall = $false
      $lastChangeAt = $null
    }
  }
}
