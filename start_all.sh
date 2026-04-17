#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$ROOT_DIR"
BFF_DIR="$ROOT_DIR/summarynotes-be"
FE_DIR="$ROOT_DIR/summarynotes-fe"

RUNTIME_DIR="$ROOT_DIR/runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

ENV_FILE="$ROOT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python}"
NPM_BIN="${NPM_BIN:-npm}"
APP_CONDA_ENV="${APP_CONDA_ENV:-}"
ENGINE_CONDA_ENV="${ENGINE_CONDA_ENV:-${APP_CONDA_ENV:-}}"
BFF_CONDA_ENV="${BFF_CONDA_ENV:-${APP_CONDA_ENV:-}}"

ENGINE_PORT="${ENGINE_PORT:-8000}"
BFF_PORT="${BFF_PORT:-9000}"
FE_PORT="${FE_PORT:-3000}"

ENGINE_PID_FILE="$PID_DIR/engine.pid"
BFF_PID_FILE="$PID_DIR/bff.pid"
FE_PID_FILE="$PID_DIR/fe.pid"

ENGINE_LOG="$LOG_DIR/engine.log"
BFF_LOG="$LOG_DIR/bff.log"
FE_LOG="$LOG_DIR/fe.log"

ensure_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "缺少命令：$cmd"
    exit 1
  fi
}

verify_started() {
  local name="$1"
  local pid="$2"
  local log_file="$3"
  sleep 2
  if kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  echo "$name 启动后立即退出，请检查日志：$log_file"
  echo "---- $name 日志尾部 ----"
  tail -n 20 "$log_file" || true
  echo "------------------------"
  exit 1
}

kill_process_tree() {
  local pid="$1"
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  if command -v pgrep >/dev/null 2>&1; then
    local child
    while IFS= read -r child; do
      if [[ -n "${child:-}" ]]; then
        kill_process_tree "$child"
      fi
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  fi

  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

get_port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti ":$port" 2>/dev/null || true
  fi
}

ensure_port_available() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(get_port_pids "$port")"
  if [[ -n "${pids:-}" ]]; then
    echo "$name 端口 $port 已被占用，开始自动清理相关 PID："
    echo "$pids"
    kill_port_processes "$name" "$port"
    sleep 1
    pids="$(get_port_pids "$port")"
    if [[ -n "${pids:-}" ]]; then
      echo "$name 端口 $port 仍然被占用，相关 PID："
      echo "$pids"
      exit 1
    fi
  fi
}

kill_port_processes() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(get_port_pids "$port")"
  if [[ -z "${pids:-}" ]]; then
    return 0
  fi

  echo "$name 端口 $port 仍被占用，开始按端口清理："
  echo "$pids"
  while IFS= read -r pid; do
    if [[ -n "${pid:-}" ]]; then
      kill_process_tree "$pid"
    fi
  done <<< "$pids"
}

ensure_command "$PYTHON_BIN"
ensure_command "$NPM_BIN"

if [[ -n "$ENGINE_CONDA_ENV" || -n "$BFF_CONDA_ENV" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "已设置 conda 环境名，但当前 shell 找不到 conda 命令。"
    exit 1
  fi
fi

is_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -z "${pid:-}" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

run_python_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local workdir="$4"
  local port="$5"
  local module="$6"
  local conda_env="$7"

  if is_running "$pid_file"; then
    echo "$name 已在运行，PID=$(cat "$pid_file")"
    return 0
  fi
  rm -f "$pid_file"
  echo "启动 $name ..."

  ensure_port_available "$name" "$port"

  local cmd=()
  if [[ -n "$conda_env" ]]; then
    cmd=(conda run -n "$conda_env" "$PYTHON_BIN" -m uvicorn "$module" --host 0.0.0.0 --port "$port")
  else
    cmd=("$PYTHON_BIN" -m uvicorn "$module" --host 0.0.0.0 --port "$port")
  fi

  (
    cd "$workdir"
    nohup "${cmd[@]}" >>"$log_file" 2>&1 &
    echo $! >"$pid_file"
  )
  local pid
  pid="$(cat "$pid_file")"
  verify_started "$name" "$pid" "$log_file"
  echo "$name 已启动，PID=$pid"
}

start_engine() {
  run_python_service "引擎服务" "$ENGINE_PID_FILE" "$ENGINE_LOG" "$ENGINE_DIR" "$ENGINE_PORT" "Api:app" "$ENGINE_CONDA_ENV"
}

start_bff() {
  run_python_service "BFF" "$BFF_PID_FILE" "$BFF_LOG" "$BFF_DIR" "$BFF_PORT" "main:app" "$BFF_CONDA_ENV"
}

start_fe() {
  if is_running "$FE_PID_FILE"; then
    echo "前端已在运行，PID=$(cat "$FE_PID_FILE")"
    return 0
  fi
  rm -f "$FE_PID_FILE"

  ensure_port_available "前端" "$FE_PORT"

  if [[ ! -f "$FE_DIR/.next/BUILD_ID" || "${BUILD_FE:-0}" == "1" ]]; then
    echo "构建前端 ..."
    (
      cd "$FE_DIR"
      "$NPM_BIN" run build >>"$FE_LOG" 2>&1
    )
  fi

  echo "启动前端 ..."
  (
    cd "$FE_DIR"
    nohup "$NPM_BIN" run start -- --hostname 0.0.0.0 --port "$FE_PORT" >>"$FE_LOG" 2>&1 &
    echo $! >"$FE_PID_FILE"
  )
  local pid
  pid="$(cat "$FE_PID_FILE")"
  verify_started "前端" "$pid" "$FE_LOG"
  echo "前端已启动，PID=$pid"
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  if ! [[ -f "$pid_file" ]]; then
    echo "$name 未运行"
    kill_port_processes "$name" "$port"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "停止 $name (PID=$pid) ..."
    kill_process_tree "$pid"
  else
    echo "$name 进程不存在，清理 PID 文件"
    kill_port_processes "$name" "$port"
  fi
  rm -f "$pid_file"
}

status_process() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    echo "$name: 运行中 (PID=$(cat "$pid_file"))"
  else
    echo "$name: 未运行"
  fi
}

case "${1:-start}" in
  start)
    start_engine
    start_bff
    start_fe
    echo "三个服务已启动。"
    echo "引擎: http://127.0.0.1:${ENGINE_PORT}"
    echo "BFF:   http://127.0.0.1:${BFF_PORT}"
    echo "FE:    http://127.0.0.1:${FE_PORT}"
    ;;
  stop)
    stop_process "前端" "$FE_PID_FILE" "$FE_PORT"
    stop_process "BFF" "$BFF_PID_FILE" "$BFF_PORT"
    stop_process "引擎服务" "$ENGINE_PID_FILE" "$ENGINE_PORT"
    echo "三个服务已停止。"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    status_process "引擎服务" "$ENGINE_PID_FILE"
    status_process "BFF" "$BFF_PID_FILE"
    status_process "前端" "$FE_PID_FILE"
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
