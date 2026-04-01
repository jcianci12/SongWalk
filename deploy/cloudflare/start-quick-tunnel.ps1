param(
  [string]$ProjectName = "songshare",
  [string]$NetworkName = "",
  [string]$ServiceUrl = "http://songshare:8080",
  [string]$ContainerName = "songshare-cloudflared",
  [string]$Image = "cloudflare/cloudflared:latest",
  [int]$WaitSeconds = 25
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($NetworkName)) {
  $NetworkName = "${ProjectName}_default"
}

function Get-DockerLogsText {
  param(
    [Parameter(Mandatory = $true)]
    [string]$TargetContainerName
  )

  return (cmd /c "docker logs $TargetContainerName 2>&1") | Out-String
}

Write-Host "Starting Cloudflare Quick Tunnel for $ServiceUrl on Docker network $NetworkName..."

$existing = docker ps -a --filter "name=^${ContainerName}$" --format "{{.ID}}"
if ($existing) {
  docker rm -f $ContainerName | Out-Null
}

docker run -d `
  --name $ContainerName `
  --network $NetworkName `
  $Image `
  tunnel --no-autoupdate --url $ServiceUrl | Out-Null

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$publicUrl = ""

while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 1
  $logs = Get-DockerLogsText -TargetContainerName $ContainerName
  $match = [regex]::Match($logs, 'https://[-a-z0-9]+\.trycloudflare\.com')
  if ($match.Success) {
    $publicUrl = $match.Value
    break
  }
}

if (-not $publicUrl) {
  Write-Warning "Tunnel started but no public URL was found in logs yet."
  Write-Host "Inspect logs with: docker logs $ContainerName"
  exit 1
}

Write-Host ""
Write-Host "Quick Tunnel ready:"
Write-Host $publicUrl
Write-Host ""
Write-Host "Stop it with:"
Write-Host "docker rm -f $ContainerName"
