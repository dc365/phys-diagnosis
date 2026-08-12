#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${WEATHER_DIAG_RUNTIME_DIR:-$ROOT_DIR/.runtime}"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  DEFAULT_PYTHON="$ROOT_DIR/.venv/bin/python"
elif [[ -x "/home/miniconda3/envs/phys/bin/python" ]]; then
  DEFAULT_PYTHON="/home/miniconda3/envs/phys/bin/python"
else
  DEFAULT_PYTHON="python3"
fi

PYTHON_BIN="${PYTHON:-$DEFAULT_PYTHON}"
API_HOST="${WEATHER_DIAG_API_HOST:-0.0.0.0}"
API_PORT="${WEATHER_DIAG_API_PORT:-11011}"
API_APP="${WEATHER_DIAG_API_APP:-backend.app.main:app}"
API_RELOAD="${WEATHER_DIAG_API_RELOAD:-0}"
START_TIMEOUT_SECONDS="${WEATHER_DIAG_START_TIMEOUT_SECONDS:-60}"
STOP_TIMEOUT_SECONDS="${WEATHER_DIAG_STOP_TIMEOUT_SECONDS:-20}"

MCP_TRANSPORT="${AREA_RISK_DSL_MCP_TRANSPORT:-http}"
MCP_HOST="${AREA_RISK_DSL_MCP_HOST:-0.0.0.0}"
MCP_PORT="${AREA_RISK_DSL_MCP_PORT:-11012}"
MCP_PATH="${AREA_RISK_DSL_MCP_PATH:-/mcp}"

SERVICES=("api" "area-risk-mcp")
API_SYSTEMD_UNIT="${WEATHER_DIAG_API_SYSTEMD_UNIT:-bdp-dm-physical-api.service}"
MCP_SYSTEMD_UNIT="${WEATHER_DIAG_MCP_SYSTEMD_UNIT:-bdp-dm-physical-mcp.service}"

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
  WEATHER_DIAG_API_PORT          API port. Default: 11011
  WEATHER_DIAG_API_RELOAD        Set 1 to pass --reload to uvicorn. Default: 0
  WEATHER_DIAG_START_TIMEOUT_SECONDS  Startup timeout. Default: 60
  WEATHER_DIAG_STOP_TIMEOUT_SECONDS   Shutdown timeout. Default: 20
  AREA_RISK_DSL_MCP_TRANSPORT    MCP transport. Default: http
  AREA_RISK_DSL_MCP_HOST         MCP host. Default: 0.0.0.0
  AREA_RISK_DSL_MCP_PORT         MCP port. Default: 11012
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

service_port() {
  case "$1" in
    api) printf '%s' "$API_PORT" ;;
    area-risk-mcp) printf '%s' "$MCP_PORT" ;;
  esac
}

systemd_unit() {
  case "$1" in
    api) printf '%s' "$API_SYSTEMD_UNIT" ;;
    area-risk-mcp) printf '%s' "$MCP_SYSTEMD_UNIT" ;;
  esac
}

uses_systemd() {
  local unit
  [[ "${WEATHER_DIAG_USE_SYSTEMD:-1}" != "0" ]] || return 1
  command -v systemctl >/dev/null 2>&1 || return 1
  unit="$(systemd_unit "$1")"
  systemctl cat "$unit" >/dev/null 2>&1
}

systemd_main_pid() {
  systemctl show -p MainPID "$(systemd_unit "$1")" 2>/dev/null | sed -n 's/^MainPID=//p'
}

start_systemd_service() {
  local service="$1" unit pid
  ensure_runtime_dirs
  unit="$(systemd_unit "$service")"
  if ! systemctl start "$unit"; then
    echo "$service failed to start through $unit" >&2
    return 1
  fi
  pid="$(systemd_main_pid "$service" || true)"
  if [[ -n "$pid" && "$pid" != "0" ]]; then
    write_pid_file "$service" "$pid"
  fi
  confirm_service_started "$service" "$(service_port "$service")"
}

listener_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  fi
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

process_parent() {
  ps -p "$1" -o ppid= 2>/dev/null | tr -d ' ' || true
}

write_pid_file() {
  local service="$1" pid="$2" file tmp
  file="$(pid_file "$service")"
  tmp="${file}.tmp.$$"
  printf '%s\n' "$pid" >"$tmp"
  mv -f "$tmp" "$file"
}

reconcile_service_pid() {
  local service="$1" file pid port listener parent command parent_command
  file="$(pid_file "$service")"
  if [[ -s "$file" ]]; then
    pid="$(cat "$file")"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    rm -f "$file"
  fi

  port="$(service_port "$service")"
  while IFS= read -r listener; do
    [[ -n "$listener" ]] || continue
    command="$(process_command "$listener")"
    parent="$(process_parent "$listener")"
    parent_command="$(process_command "$parent")"
    if [[ "$parent_command" == *"$ROOT_DIR/scripts/api_supervisor.py"* ]]; then
      write_pid_file "$service" "$parent"
      return 0
    fi
    if [[ "$service" == "api" && "$command" == *"-m uvicorn $API_APP"* ]]; then
      write_pid_file "$service" "$listener"
      return 0
    fi
    if [[ "$service" == "area-risk-mcp" && "$command" == *"-m weather_diag.mcp.area_risk_dsl_mcp"* ]]; then
      write_pid_file "$service" "$listener"
      return 0
    fi
  done < <(listener_pids "$port")
  return 1
}

log_file() {
  printf '%s/%s.log' "$LOG_DIR" "$1"
}

is_running() {
  local service="$1"
  local file
  file="$(pid_file "$service")"
  reconcile_service_pid "$service" || return 1
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
  if command -v lsof >/dev/null 2>&1; then
    local listeners
    listeners="$(listener_pids "$API_PORT")"
    if [[ -n "$listeners" ]]; then
      echo "$service cannot start: port $API_PORT is already used by unmanaged pid(s): ${listeners//$'\n'/,}" >&2
      return 1
    fi
  fi

  local command=("$PYTHON_BIN" -m uvicorn "$API_APP" --host "$API_HOST" --port "$API_PORT")
  if [[ "$API_RELOAD" == "1" || "$API_RELOAD" == "true" ]]; then
    command+=(--reload)
  fi

  (
    cd "$ROOT_DIR"
    export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
    export PYTHONFAULTHANDLER="${PYTHONFAULTHANDLER:-1}"
    nohup "$PYTHON_BIN" "$ROOT_DIR/scripts/api_supervisor.py" --label api -- "${command[@]}" >>"$logfile" 2>&1 &
    write_pid_file "$service" "$!"
  )
  confirm_service_started "$service" "$API_PORT"
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
  if command -v lsof >/dev/null 2>&1; then
    local listeners
    listeners="$(listener_pids "$MCP_PORT")"
    if [[ -n "$listeners" ]]; then
      echo "$service cannot start: port $MCP_PORT is already used by unmanaged pid(s): ${listeners//$'\n'/,}" >&2
      return 1
    fi
  fi

  local command=("$PYTHON_BIN" -m weather_diag.mcp.area_risk_dsl_mcp)

  (
    cd "$ROOT_DIR"
    export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
    export AREA_RISK_DSL_MCP_TRANSPORT="$MCP_TRANSPORT"
    export AREA_RISK_DSL_MCP_HOST="$MCP_HOST"
    export AREA_RISK_DSL_MCP_PORT="$MCP_PORT"
    export AREA_RISK_DSL_MCP_PATH="$MCP_PATH"
    nohup "$PYTHON_BIN" "$ROOT_DIR/scripts/api_supervisor.py" --label area-risk-mcp -- "${command[@]}" >>"$logfile" 2>&1 &
    write_pid_file "$service" "$!"
  )
  confirm_service_started "$service" "$MCP_PORT"
}

confirm_service_started() {
  local service="$1" port="$2" pid deadline
  deadline=$((SECONDS + START_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if uses_systemd "$service"; then
      if [[ "$(systemctl is-active "$(systemd_unit "$service")" 2>/dev/null || true)" != "active" ]]; then
        break
      fi
      pid="$(systemd_main_pid "$service" || true)"
    else
      pid="$(service_pid "$service")"
      if ! is_running "$service"; then
        break
      fi
    fi
    if ! command -v lsof >/dev/null 2>&1 || [[ -n "$(listener_pids "$port")" ]]; then
      echo "$service started (pid $pid, log $(log_file "$service"))"
      return 0
    fi
    sleep 1
  done
  echo "$service failed to start or bind port $port within ${START_TIMEOUT_SECONDS}s. Last log lines:" >&2
  if uses_systemd "$service"; then
    journalctl -u "$(systemd_unit "$service")" -n 40 --no-pager >&2 || true
  else
    tail -n 40 "$(log_file "$service")" >&2 || true
  fi
  stop_service "$service" >/dev/null || true
  return 1
}

start_service() {
  if uses_systemd "$1"; then
    start_systemd_service "$1"
    return
  fi
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
  if uses_systemd "$service"; then
    local unit port deadline
    unit="$(systemd_unit "$service")"
    port="$(service_port "$service")"
    systemctl stop "$unit" || true
    deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
    while (( SECONDS < deadline )); do
      if [[ -z "$(listener_pids "$port")" ]]; then
        rm -f "$pidfile"
        echo "$service stopped"
        return 0
      fi
      sleep 1
    done
    echo "$service failed to stop through $unit or release port $port" >&2
    return 1
  fi
  if ! is_running "$service"; then
    rm -f "$pidfile"
    echo "$service stopped"
    return 0
  fi

  pid="$(service_pid "$service")"
  local port deadline listener managed_listeners
  port="$(service_port "$service")"
  managed_listeners="$(listener_pids "$port")"
  kill "$pid" >/dev/null 2>&1 || true
  deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  while IFS= read -r listener; do
    [[ -n "$listener" ]] || continue
    if kill -0 "$listener" >/dev/null 2>&1; then
      kill "$listener" >/dev/null 2>&1 || true
    fi
  done <<<"$managed_listeners"
  rm -f "$pidfile"
  if [[ -z "$(listener_pids "$port")" ]]; then
    echo "$service stopped"
    return 0
  fi
  echo "$service failed to release port $port" >&2
  return 1
}

status_service() {
  ensure_runtime_dirs
  local service="$1"
  if uses_systemd "$service"; then
    local unit state pid
    unit="$(systemd_unit "$service")"
    state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    pid="$(systemd_main_pid "$service" || true)"
    if [[ "$state" == "active" ]]; then
      [[ -n "$pid" && "$pid" != "0" ]] && write_pid_file "$service" "$pid"
      printf '%-14s running pid=%s manager=systemd unit=%s log=%s\n' "$service" "$pid" "$unit" "$(log_file "$service")"
      return 0
    fi
    printf '%-14s stopped manager=systemd unit=%s log=%s\n' "$service" "$unit" "$(log_file "$service")"
    return 0
  fi
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
      if uses_systemd "$service"; then
        echo "==> $service (journalctl -u $(systemd_unit "$service"))"
        journalctl -u "$(systemd_unit "$service")" -n 80 --no-pager
      else
        echo "==> $service ($(log_file "$service"))"
        tail -n 80 "$(log_file "$service")" 2>/dev/null || true
      fi
    done
    return 0
  fi
  if uses_systemd "$target"; then
    journalctl -u "$(systemd_unit "$target")" -n 120 -f
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
      local failed=0
      while IFS= read -r service; do
        if ! start_service "$service"; then failed=1; fi
      done < <(targets_for "$target")
      return "$failed"
      ;;
    stop)
      local failed=0
      while IFS= read -r service; do
        if ! stop_service "$service"; then failed=1; fi
      done < <(targets_for "$target" | sort -r)
      return "$failed"
      ;;
    restart)
      local failed=0
      run_action stop "$target" || failed=1
      run_action start "$target" || failed=1
      return "$failed"
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
