param(
  [ValidateSet("", "docker", "python", IgnoreCase = $true)]
  [string]$Runtime = "",
  [int]$Port = 8080,
  [string]$ProjectName = "songshare",
  [string]$TunnelContainerName = "songshare-cloudflared",
  [int]$StartupWaitSeconds = 60,
  [int]$TunnelWaitSeconds = 25
)

$ErrorActionPreference = "Stop"

if (-not $PSBoundParameters.ContainsKey("Port") -and $env:SONGSHARE_PUBLISHED_PORT) {
  $Port = [int]$env:SONGSHARE_PUBLISHED_PORT
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DataDir = Join-Path $RepoRoot "songshare-data"
$RuntimeDir = Join-Path $DataDir "runtime"
$StdoutLog = Join-Path $RuntimeDir "songshare-python.stdout.log"
$StderrLog = Join-Path $RuntimeDir "songshare-python.stderr.log"
$PidFile = Join-Path $RuntimeDir "songshare-python.pid"
$OwnerUrlFile = Join-Path $DataDir "owner-url.txt"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Fail {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Message,
    [string[]]$Details = @()
  )

  Write-Host ""
  Write-Host "ERROR: $Message" -ForegroundColor Red
  foreach ($detail in $Details) {
    if (-not [string]::IsNullOrWhiteSpace($detail)) {
      Write-Host $detail
    }
  }
  exit 1
}

function Require-Command {
  param(
    [Parameter(Mandatory = $true)]
    [string]$CommandName,
    [string]$Hint = ""
  )

  if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
    $details = @()
    if ($Hint) {
      $details += $Hint
    }
    Fail -Message "Required command '$CommandName' was not found." -Details $details
  }
}

function Invoke-Captured {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [string[]]$Arguments = @()
  )

  $output = & $FilePath @Arguments 2>&1 | Out-String
  return @{
    ExitCode = $LASTEXITCODE
    Output = $output.TrimEnd()
  }
}

function Choose-Runtime {
  if ($Runtime) {
    return $Runtime.ToLowerInvariant()
  }

  while ($true) {
    $answer = Read-Host "Run Songshare with Docker or Python? [docker/python]"
    switch ($answer.Trim().ToLowerInvariant()) {
      "docker" { return "docker" }
      "d" { return "docker" }
      "python" { return "python" }
      "p" { return "python" }
      default { Write-Host "Enter 'docker' or 'python'." }
    }
  }
}

function Test-SongshareReady {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url
  )

  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
    return $response.Content -match "Songshare"
  }
  catch {
    return $false
  }
}

function Get-OwnerPath {
  if (-not (Test-Path $OwnerUrlFile)) {
    return ""
  }

  $match = Select-String -Path $OwnerUrlFile -Pattern '^/owner/[A-Za-z0-9_-]+$' | Select-Object -Last 1
  if ($match) {
    return $match.Line.Trim()
  }
  return ""
}

function Show-PythonLogs {
  if (Test-Path $StdoutLog) {
    $stdout = Get-Content $StdoutLog -Tail 40 -ErrorAction SilentlyContinue | Out-String
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
      Write-Host ""
      Write-Host "songshare stdout:"
      Write-Host $stdout.TrimEnd()
    }
  }

  if (Test-Path $StderrLog) {
    $stderr = Get-Content $StderrLog -Tail 40 -ErrorAction SilentlyContinue | Out-String
    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
      Write-Host ""
      Write-Host "songshare stderr:"
      Write-Host $stderr.TrimEnd()
    }
  }
}

function Wait-ForSongshare {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$WaitSeconds = 60,
    [System.Diagnostics.Process]$Process = $null,
    [string]$FailureHint = ""
  )

  $deadline = (Get-Date).AddSeconds($WaitSeconds)

  while ((Get-Date) -lt $deadline) {
    if (Test-SongshareReady -Url $Url) {
      return
    }

    if ($Process) {
      $Process.Refresh()
      if ($Process.HasExited) {
        Show-PythonLogs
        Fail -Message "Songshare exited before it became ready." -Details @($FailureHint)
      }
    }

    Start-Sleep -Seconds 1
  }

  if ($Process) {
    Show-PythonLogs
  }

  Fail -Message "Timed out waiting for Songshare at $Url." -Details @($FailureHint)
}

function Resolve-PythonLaunch {
  $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return @{
      FilePath = $venvPython
      Arguments = @()
      DisplayName = $venvPython
    }
  }

  if (Get-Command python -ErrorAction SilentlyContinue) {
    return @{
      FilePath = "python"
      Arguments = @()
      DisplayName = "python"
    }
  }

  if (Get-Command py -ErrorAction SilentlyContinue) {
    return @{
      FilePath = "py"
      Arguments = @("-3")
      DisplayName = "py -3"
    }
  }

  Fail -Message "No Python launcher was found." -Details @("Create .venv first or install a 'python' command on PATH.")
}

function Start-PythonRuntime {
  param(
    [Parameter(Mandatory = $true)]
    [int]$LocalPort
  )

  $localUrl = "http://127.0.0.1:$LocalPort/"
  if (Test-SongshareReady -Url $localUrl) {
    Write-Host "Songshare is already responding on $localUrl. Reusing the existing Python/local instance."
    return $null
  }

  $python = Resolve-PythonLaunch
  $importCheck = Invoke-Captured -FilePath $python.FilePath -Arguments ($python.Arguments + @("-c", "import songshare"))
  if ($importCheck.ExitCode -ne 0) {
    Fail -Message "Python could not import the Songshare app." -Details @(
      "Tried: $($python.DisplayName)",
      $importCheck.Output,
      "Install dependencies with: pip install -r requirements.txt"
    )
  }

  Remove-Item -LiteralPath $StdoutLog, $StderrLog -Force -ErrorAction SilentlyContinue

  Write-Host "Starting Songshare with $($python.DisplayName)..."
  $previousSongsharePort = $env:SONGSHARE_PORT
  $env:SONGSHARE_PORT = [string]$LocalPort
  $process = Start-Process `
    -FilePath $python.FilePath `
    -ArgumentList ($python.Arguments + @("-m", "songshare")) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru
  if ($null -eq $previousSongsharePort) {
    Remove-Item Env:\SONGSHARE_PORT -ErrorAction SilentlyContinue
  }
  else {
    $env:SONGSHARE_PORT = $previousSongsharePort
  }

  Set-Content -Path $PidFile -Value $process.Id -Encoding ascii
  Wait-ForSongshare -Url $localUrl -WaitSeconds $StartupWaitSeconds -Process $process -FailureHint "Inspect logs in $StdoutLog and $StderrLog."
  return $process
}

function Show-DockerComposeLogs {
  $logs = Invoke-Captured -FilePath "docker" -Arguments @("compose", "logs", "--tail=80", "songshare")
  if (-not [string]::IsNullOrWhiteSpace($logs.Output)) {
    Write-Host ""
    Write-Host "docker compose logs --tail=80 songshare"
    Write-Host $logs.Output
  }
}

function Start-DockerRuntime {
  param(
    [Parameter(Mandatory = $true)]
    [int]$LocalPort
  )

  $localUrl = "http://127.0.0.1:$LocalPort/"
  if (Test-SongshareReady -Url $localUrl) {
    Write-Host "Songshare is already responding on $localUrl. Reusing the existing local service."
    return
  }

  Write-Host "Starting Songshare with Docker Compose..."
  $previousPublishedPort = $env:SONGSHARE_PUBLISHED_PORT
  $env:SONGSHARE_PUBLISHED_PORT = [string]$LocalPort
  $result = Invoke-Captured -FilePath "docker" -Arguments @("compose", "up", "--build", "-d")
  if ($null -eq $previousPublishedPort) {
    Remove-Item Env:\SONGSHARE_PUBLISHED_PORT -ErrorAction SilentlyContinue
  }
  else {
    $env:SONGSHARE_PUBLISHED_PORT = $previousPublishedPort
  }
  if ($result.ExitCode -ne 0) {
    Fail -Message "docker compose up failed." -Details @($result.Output)
  }

  $deadline = (Get-Date).AddSeconds($StartupWaitSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-SongshareReady -Url $localUrl) {
      return
    }
    Start-Sleep -Seconds 1
  }

  Show-DockerComposeLogs
  Fail -Message "Timed out waiting for Songshare at $localUrl." -Details @("Inspect 'docker compose logs --tail=80 songshare' for details.")
}

function Start-QuickTunnel {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("docker", "python")]
    [string]$SelectedRuntime,
    [Parameter(Mandatory = $true)]
    [int]$LocalPort
  )

  $existing = Invoke-Captured -FilePath "docker" -Arguments @("ps", "-a", "--filter", "name=^${TunnelContainerName}$", "--format", "{{.ID}}")
  if ($existing.Output) {
    [void](Invoke-Captured -FilePath "docker" -Arguments @("rm", "-f", $TunnelContainerName))
  }

  $dockerArgs = @("run", "-d", "--name", $TunnelContainerName)
  if ($SelectedRuntime -eq "docker") {
    $dockerArgs += @("--network", "${ProjectName}_default")
    $serviceUrl = "http://songshare:8080"
  }
  else {
    $dockerArgs += @("--add-host", "host.docker.internal:host-gateway")
    $serviceUrl = "http://host.docker.internal:$LocalPort"
  }

  $dockerArgs += @("cloudflare/cloudflared:latest", "tunnel", "--no-autoupdate", "--url", $serviceUrl)

  Write-Host "Starting Cloudflare Quick Tunnel..."
  $start = Invoke-Captured -FilePath "docker" -Arguments $dockerArgs
  if ($start.ExitCode -ne 0) {
    Fail -Message "Failed to start the Cloudflare Quick Tunnel container." -Details @($start.Output)
  }

  $deadline = (Get-Date).AddSeconds($TunnelWaitSeconds)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1

    $logs = Invoke-Captured -FilePath "docker" -Arguments @("logs", $TunnelContainerName)
    $match = [regex]::Match($logs.Output, 'https://[-a-z0-9]+\.trycloudflare\.com')
    if ($match.Success) {
      return $match.Value
    }

    $state = Invoke-Captured -FilePath "docker" -Arguments @("inspect", "-f", "{{.State.Running}}", $TunnelContainerName)
    if ($state.ExitCode -eq 0 -and $state.Output -eq "false") {
      Fail -Message "The Cloudflare Quick Tunnel container exited before a URL was published." -Details @($logs.Output)
    }
  }

  $finalLogs = Invoke-Captured -FilePath "docker" -Arguments @("logs", $TunnelContainerName)
  Fail -Message "Timed out waiting for the Cloudflare Quick Tunnel URL." -Details @(
    "Inspect logs with: docker logs $TunnelContainerName",
    $finalLogs.Output
  )
}

$selectedRuntime = Choose-Runtime

Require-Command -CommandName "docker" -Hint "Docker is required for the Quick Tunnel container."
if ($selectedRuntime -eq "docker") {
  $composeCheck = Invoke-Captured -FilePath "docker" -Arguments @("compose", "version")
  if ($composeCheck.ExitCode -ne 0) {
    Fail -Message "Docker Compose is required for docker mode." -Details @($composeCheck.Output)
  }
}

Push-Location $RepoRoot
try {
  if ($selectedRuntime -eq "docker") {
    Start-DockerRuntime -LocalPort $Port
  }
  else {
    Start-PythonRuntime -LocalPort $Port | Out-Null
  }

  $publicUrl = Start-QuickTunnel -SelectedRuntime $selectedRuntime -LocalPort $Port
  $ownerPath = Get-OwnerPath

  Write-Host ""
  Write-Host "Songshare is ready."
  Write-Host "Local URL: http://localhost:$Port/"
  Write-Host "Public URL: $publicUrl"
  if ($ownerPath) {
    Write-Host "Private owner URL: $publicUrl$ownerPath"
  }
  Write-Host ""
  Write-Host "Stop the tunnel with:"
  Write-Host "docker rm -f $TunnelContainerName"
}
finally {
  Pop-Location
}
