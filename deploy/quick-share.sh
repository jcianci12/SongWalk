#!/usr/bin/env bash
set -euo pipefail

RUNTIME="${1:-}"
PORT="${SONGSHARE_PUBLISHED_PORT:-8080}"
PROJECT_NAME="songshare"
TUNNEL_CONTAINER_NAME="songshare-cloudflared"
STARTUP_WAIT_SECONDS=60
TUNNEL_WAIT_SECONDS=25

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT_DIR/songshare-data"
RUNTIME_DIR="$DATA_DIR/runtime"
STDOUT_LOG="$RUNTIME_DIR/songshare-python.stdout.log"
STDERR_LOG="$RUNTIME_DIR/songshare-python.stderr.log"
PID_FILE="$RUNTIME_DIR/songshare-python.pid"
OWNER_URL_FILE="$DATA_DIR/owner-url.txt"

mkdir -p "$RUNTIME_DIR"

fail() {
  echo >&2
  echo "ERROR: $1" >&2
  shift || true
  for detail in "$@"; do
    if [[ -n "$detail" ]]; then
      echo "$detail" >&2
    fi
  done
  exit 1
}

require_command() {
  local command_name="$1"
  local hint="${2:-}"
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command '$command_name' was not found." "$hint"
}

choose_runtime() {
  if [[ -n "$RUNTIME" ]]; then
    case "${RUNTIME,,}" in
      docker|python)
        echo "${RUNTIME,,}"
        return
        ;;
      *)
        fail "Invalid runtime '$RUNTIME'." "Use 'docker' or 'python'."
        ;;
    esac
  fi

  while true; do
    read -r -p "Run Songshare with Docker or Python? [docker/python] " answer
    case "${answer,,}" in
      docker|d)
        echo "docker"
        return
        ;;
      python|p)
        echo "python"
        return
        ;;
      *)
        echo "Enter 'docker' or 'python'."
        ;;
    esac
  done
}

test_songshare_ready() {
  local body
  body="$(curl -fsSL --max-time 3 -L "http://127.0.0.1:${PORT}/" 2>/dev/null || true)"
  [[ "$body" == *Songshare* ]]
}

show_python_logs() {
  if [[ -f "$STDOUT_LOG" ]]; then
    local stdout_tail
    stdout_tail="$(tail -n 40 "$STDOUT_LOG" 2>/dev/null || true)"
    [[ -z "$stdout_tail" ]] || {
      echo
      echo "songshare stdout:"
      echo "$stdout_tail"
    }
  fi

  if [[ -f "$STDERR_LOG" ]]; then
    local stderr_tail
    stderr_tail="$(tail -n 40 "$STDERR_LOG" 2>/dev/null || true)"
    [[ -z "$stderr_tail" ]] || {
      echo
      echo "songshare stderr:"
      echo "$stderr_tail"
    }
  fi
}

wait_for_songshare() {
  local end_time="$((SECONDS + STARTUP_WAIT_SECONDS))"
  local pid="${1:-}"
  local failure_hint="${2:-}"

  while (( SECONDS < end_time )); do
    if test_songshare_ready; then
      return 0
    fi

    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      show_python_logs
      fail "Songshare exited before it became ready." "$failure_hint"
    fi

    sleep 1
  done

  if [[ -n "$pid" ]]; then
    show_python_logs
  fi

  fail "Timed out waiting for Songshare at http://127.0.0.1:${PORT}/." "$failure_hint"
}

resolve_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/.venv/bin/python"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  fail "No Python launcher was found." "Create .venv first or install python3/python on PATH."
}

start_python_runtime() {
  if test_songshare_ready; then
    echo "Songshare is already responding on http://127.0.0.1:${PORT}/. Reusing the existing Python/local instance."
    return
  fi

  local python_bin
  python_bin="$(resolve_python)"
  local import_output
  if ! import_output="$(cd "$ROOT_DIR" && "$python_bin" -c 'import songshare' 2>&1)"; then
    fail "Python could not import the Songshare app." "Tried: $python_bin" "$import_output" "Install dependencies with: pip install -r requirements.txt"
  fi

  rm -f "$STDOUT_LOG" "$STDERR_LOG"
  echo "Starting Songshare with ${python_bin}..."
  (
    cd "$ROOT_DIR"
    SONGSHARE_PORT="$PORT" nohup "$python_bin" -m songshare >"$STDOUT_LOG" 2>"$STDERR_LOG" &
    echo $! >"$PID_FILE"
  )

  local pid
  pid="$(cat "$PID_FILE")"
  wait_for_songshare "$pid" "Inspect logs in $STDOUT_LOG and $STDERR_LOG."
}

show_docker_logs() {
  local logs
  logs="$(cd "$ROOT_DIR" && docker compose logs --tail=80 songshare 2>&1 || true)"
  [[ -z "$logs" ]] || {
    echo
    echo "docker compose logs --tail=80 songshare"
    echo "$logs"
  }
}

start_docker_runtime() {
  if test_songshare_ready; then
    echo "Songshare is already responding on http://127.0.0.1:${PORT}/. Reusing the existing local service."
    return
  fi

  echo "Starting Songshare with Docker Compose..."
  if ! (cd "$ROOT_DIR" && SONGSHARE_PUBLISHED_PORT="$PORT" docker compose up --build -d); then
    fail "docker compose up failed."
  fi

  local end_time="$((SECONDS + STARTUP_WAIT_SECONDS))"
  while (( SECONDS < end_time )); do
    if test_songshare_ready; then
      return
    fi
    sleep 1
  done

  show_docker_logs
  fail "Timed out waiting for Songshare at http://127.0.0.1:${PORT}/." "Inspect 'docker compose logs --tail=80 songshare' for details."
}

start_quick_tunnel() {
  local selected_runtime="$1"
  local service_url
  local docker_args=(run -d --name "$TUNNEL_CONTAINER_NAME")

  local existing
  existing="$(docker ps -a --filter "name=^${TUNNEL_CONTAINER_NAME}$" --format '{{.ID}}' || true)"
  if [[ -n "$existing" ]]; then
    docker rm -f "$TUNNEL_CONTAINER_NAME" >/dev/null
  fi

  if [[ "$selected_runtime" == "docker" ]]; then
    docker_args+=(--network "${PROJECT_NAME}_default")
    service_url="http://songshare:8080"
  else
    docker_args+=(--add-host host.docker.internal:host-gateway)
    service_url="http://host.docker.internal:${PORT}"
  fi

  docker_args+=(cloudflare/cloudflared:latest tunnel --no-autoupdate --url "$service_url")

  echo "Starting Cloudflare Quick Tunnel..." >&2
  if ! docker "${docker_args[@]}" >/dev/null; then
    fail "Failed to start the Cloudflare Quick Tunnel container."
  fi

  local end_time="$((SECONDS + TUNNEL_WAIT_SECONDS))"
  while (( SECONDS < end_time )); do
    sleep 1
    local logs
    logs="$(docker logs "$TUNNEL_CONTAINER_NAME" 2>&1 || true)"
    local public_url
    public_url="$(grep -oE 'https://[-a-z0-9]+\.trycloudflare\.com' <<<"$logs" | head -n 1 || true)"
    if [[ -n "$public_url" ]]; then
      echo "$public_url"
      return
    fi

    local running
    running="$(docker inspect -f '{{.State.Running}}' "$TUNNEL_CONTAINER_NAME" 2>/dev/null || true)"
    if [[ "$running" == "false" ]]; then
      fail "The Cloudflare Quick Tunnel container exited before a URL was published." "$logs"
    fi
  done

  local final_logs
  final_logs="$(docker logs "$TUNNEL_CONTAINER_NAME" 2>&1 || true)"
  fail "Timed out waiting for the Cloudflare Quick Tunnel URL." "Inspect logs with: docker logs $TUNNEL_CONTAINER_NAME" "$final_logs"
}

get_owner_path() {
  [[ -f "$OWNER_URL_FILE" ]] || return 0
  grep -E '^/owner/[A-Za-z0-9_-]+$' "$OWNER_URL_FILE" | tail -n 1 || true
}

SELECTED_RUNTIME="$(choose_runtime)"

require_command docker "Docker is required for the Quick Tunnel container."
require_command curl "curl is required for readiness checks."
if [[ "$SELECTED_RUNTIME" == "docker" ]]; then
  (cd "$ROOT_DIR" && docker compose version >/dev/null 2>&1) || fail "Docker Compose is required for docker mode."
fi

if [[ "$SELECTED_RUNTIME" == "docker" ]]; then
  start_docker_runtime
else
  start_python_runtime
fi

PUBLIC_URL="$(start_quick_tunnel "$SELECTED_RUNTIME")"
OWNER_PATH="$(get_owner_path)"

echo
echo "Songshare is ready."
echo "Local URL: http://localhost:${PORT}/"
echo "Public URL: $PUBLIC_URL"
if [[ -n "$OWNER_PATH" ]]; then
  echo "Private owner URL: ${PUBLIC_URL}${OWNER_PATH}"
fi
echo
echo "Stop the tunnel with:"
echo "docker rm -f $TUNNEL_CONTAINER_NAME"
