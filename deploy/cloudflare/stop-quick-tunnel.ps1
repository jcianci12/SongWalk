param(
  [string]$ContainerName = "songshare-cloudflared"
)

$ErrorActionPreference = "Stop"

$existing = docker ps -a --filter "name=^${ContainerName}$" --format "{{.ID}}"
if (-not $existing) {
  Write-Host "No Quick Tunnel container named $ContainerName is running."
  exit 0
}

docker rm -f $ContainerName | Out-Null
Write-Host "Stopped $ContainerName."
