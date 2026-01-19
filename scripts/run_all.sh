#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
PID_DIR="${LOG_DIR}"

mkdir -p "${LOG_DIR}"

start_process() {
  local name="$1"
  local cmd="$2"
  local log_file="${LOG_DIR}/${name}.log"
  local pid_file="${PID_DIR}/${name}.pid"

  if [[ -f "${pid_file}" ]]; then
    local existing_pid
    existing_pid="$(cat "${pid_file}")"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
      echo "${name} already running (pid ${existing_pid})."
      return
    fi
  fi

  nohup bash -c "cd '${ROOT_DIR}' && ${cmd}" >"${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${pid_file}"
  echo "Started ${name} (pid ${pid}). Log: ${log_file}"
}

start_process "monitor" "uv run monitor.py"
start_process "admin_bot" "uv run admin_bot.py"
