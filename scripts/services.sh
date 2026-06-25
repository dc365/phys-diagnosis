#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${WEATHER_DIAG_RUNTIME_DIR:-$ROOT_DIR/.runtime}"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  DEFAULT_PYTHON="$ROOT_DIR/.venv/bin/python"
else
  DEFAULT_PYTHON="python3"
fi

PYTHON_BIN="${PYTHON:-$DEFAULT_PYTHON}"
API_HOST="${WEATHER_DIAG_API_HOST:-0.0.0.0}"
API_PORT="${WEATHER_DIAG_API_PORT:-11011}"
API_APP="${WEATHER_DIAG_API_APP:-backend.app.main:app}"
API_RELOAD="${WEATHER_DIAG_API_RELOAD:-0}"

MCP_TRANSPORT="${AREA_RISK_DSL_MCP_TRANSPORT:-http}"
MCP_HOST="${AREA_RISK_DSL_MCP_HOST:-0.0.0.0}"
MCP_PORT="${AREA_RISK_DSL_MCP_PORT:-11012}"
MCP_PATH="${AREA_RISK_DSL_MCP_PATH:-/mcp}"

SERVICES=("api" "area-risk-mcp")

usage() {
  cat <<EOF
Usage:
  scripts/services.sh start|stop|restart|status|logs [all|api|area-risk-mcp]

Services:
  api             FastAPI backend, default http://0.0.0.0:${API_PORT}
  area-risk-mcp   Town risk DSL MCP, default AREA_RISK_DSL_MCP_TRANSPORT=http, http://0.0.0.0:${MCP_PORT}${MCP_PATH}

Environment:
  PYTHON                         Python executable. Default: .venv/bin/python, then python3
  WEATHER_DIAG_API_HOST          API host. Default: 0.0.0.0
  WEATHER_DIAG_API_PORT          API port. Default: 8000
  WEATHER_DIAG_API_RELOAD        Set 1 to pass --reload to uvicorn. Default: 0
  AREA_RISK_DSL_MCP_TRANSPORT    MCP transport. Default: http
  AREA_RISK_DSL_MCP_HOST         MCP host. Default: 0.0.0.0
  AREA_RISK_DSL_MCP_PORT         MCP port. Default: 11011
  AREA_RISK_DSL_MCP_PATH         MCP path. Default: /mcp
  WEATHER_DIAG_RUNTIME_DIR       PID/log directory. Default: .runtime

Examples:
  scripts/services.sh start
  scripts/services.sh restart area-risk-mcp
  scripts/services.sh status
  scripts/services.sh logs api
EOF
}

ensure_runtime_dirs() {
  mkdir -p "$PID_DIR" "$LOG_DIR"
}

pid_file() {
  printf '%s/%s.pid' "$PID_DIR" "$1"
}

log_file() {
  printf '%s/%s.log' "$LOG_DIR" "$1"
}

is_running() {
  local service="$1"
  local file
  file="$(pid_file "$service")"
  [[ -s "$file" ]] || return 1
  local pid
  pid="$(cat "$file")"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

service_pid() {
  local file
  file="$(pid_file "$1")"
  [[ -s "$file" ]] && cat "$file" || true
}

normalize_target() {
  local target="${1:-all}"
  case "$target" in
    all|api|area-risk-mcp)
      printf '%s' "$target"
      ;;
    mcp|risk-mcp|town-risk-mcp)
      printf 'area-risk-mcp'
      ;;
    *)
      echo "unknown service: $target" >&2
      exit 2
      ;;
  esac
}

targets_for() {
  local target
  target="$(normalize_target "${1:-all}")"
  if [[ "$target" == "all" ]]; then
    printf '%s\n' "${SERVICES[@]}"
  else
    printf '%s\n' "$target"
  fi
}

start_api() {
  ensure_runtime_dirs
  local service="api"
  local pidfile logfile
  pidfile="$(pid_file "$service")"
  logfile="$(log_file "$service")"
  if is_running "$service"; then
    echo "$service already running (pid $(service_pid "$service"))"
    return 0
  fi

  local command=("$PYTHON_BIN" -m uvicorn "$API_APP" --host "$API_HOST" --port "$API_PORT")
  if [[ "$API_RELOAD" == "1" || "$API_RELOAD" == "true" ]]; then
    command+=(--reload)
  fi

  (
    cd "$ROOT_DIR"
    export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
    nohup "${command[@]}" >>"$logfile" 2>&1 &
    echo $! >"$pidfile"
  )
  confirm_started "$service"
}

start_area_risk_mcp() {
  ensure_runtime_dirs
  local service="area-risk-mcp"
  local pidfile logfile
  pidfile="$(pid_file "$service")"
  logfile="$(log_file "$service")"
  if is_running "$service"; then
    echo "$service already running (pid $(service_pid "$service"))"
    return 0
  fi

  (
    cd "$ROOT_DIR"
    export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
    export AREA_RISK_DSL_MCP_TRANSPORT="$MCP_TRANSPORT"
    export AREA_RISK_DSL_MCP_HOST="$MCP_HOST"
    export AREA_RISK_DSL_MCP_PORT="$MCP_PORT"
    export AREA_RISK_DSL_MCP_PATH="$MCP_PATH"
    nohup "$PYTHON_BIN" -m weather_diag.mcp.area_risk_dsl_mcp >>"$logfile" 2>&1 &
    echo $! >"$pidfile"
  )
  confirm_started "$service"
}

confirm_started() {
  local service="$1"
  sleep 1
  if is_running "$service"; then
    echo "$service started (pid $(service_pid "$service"), log $(log_file "$service"))"
    return 0
  fi
  echo "$service failed to start. Last log lines:" >&2
  tail -n 40 "$(log_file "$service")" >&2 || true
  return 1
}

start_service() {
  case "$1" in
    api) start_api ;;
    area-risk-mcp) start_area_risk_mcp ;;
  esac
}

stop_service() {
  ensure_runtime_dirs
  local service="$1"
  local pidfile pid
  pidfile="$(pid_file "$service")"
  if ! is_running "$service"; then
    rm -f "$pidfile"
    echo "$service stopped"
    return 0
  fi

  pid="$(service_pid "$service")"
  kill "$pid" >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$pidfile"
      echo "$service stopped"
      return 0
    fi
    sleep 1
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pidfile"
  echo "$service force stopped"
}

status_service() {
  ensure_runtime_dirs
  local service="$1"
  if is_running "$service"; then
    printf '%-14s running pid=%s log=%s\n' "$service" "$(service_pid "$service")" "$(log_file "$service")"
  else
    printf '%-14s stopped log=%s\n' "$service" "$(log_file "$service")"
  fi
}

show_logs() {
  ensure_runtime_dirs
  local target
  target="$(normalize_target "${1:-all}")"
  if [[ "$target" == "all" ]]; then
    for service in "${SERVICES[@]}"; do
      echo "==> $service ($(log_file "$service"))"
      tail -n 80 "$(log_file "$service")" 2>/dev/null || true
    done
    return 0
  fi
  tail -n 120 -f "$(log_file "$target")"
}

run_action() {
  local action="$1"
  local target="${2:-all}"
  local service
  case "$action" in
    start)
      while IFS= read -r service; do start_service "$service"; done < <(targets_for "$target")
      ;;
    stop)
      while IFS= read -r service; do stop_service "$service"; done < <(targets_for "$target" | sort -r)
      ;;
    restart)
      run_action stop "$target"
      run_action start "$target"
      ;;
    status)
      while IFS= read -r service; do status_service "$service"; done < <(targets_for "$target")
      ;;
    logs)
      show_logs "$target"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

run_action "${1:---help}" "${2:-all}"
