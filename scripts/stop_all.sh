#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"

stop_process() {
  local name="$1"
  local pid_file="${LOG_DIR}/${name}.pid"

  if [[ ! -f "${pid_file}" ]]; then
    echo "${name} not running (pid file missing)."
    return
  fi

  local pid
  pid="$(cat "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    echo "${name} not running (pid empty)."
    rm -f "${pid_file}"
    return
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}"
    echo "Stopped ${name} (pid ${pid})."
  else
    echo "${name} not running (stale pid ${pid})."
  fi
  rm -f "${pid_file}"
}

stop_process "monitor"
stop_process "admin_bot"
