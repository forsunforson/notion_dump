#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"

fatal() {
  echo "❌ $*" 1>&2
  exit 1
}

ensure_rclone() {
  if command -v rclone >/dev/null 2>&1; then
    return 0
  fi

  echo "🧰 rclone not found; installing..."
  if ! command -v curl >/dev/null 2>&1; then
    fatal "curl not found; install curl first."
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    fatal "sudo not found; install rclone manually or rerun as a user with sudo."
  fi

  curl -fsSL https://rclone.org/install.sh | sudo bash

  if ! command -v rclone >/dev/null 2>&1; then
    fatal "rclone install failed; ensure the official install script succeeded."
  fi
}

load_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    fatal "Missing .env at $ENV_FILE. Copy $PROJECT_ROOT/.env.example to $ENV_FILE and fill in tokens."
  fi

  set -a
  . "$ENV_FILE"
  set +a
}

require_env() {
  local k="$1"
  if [ -z "${!k:-}" ]; then
    fatal "Missing required env var: $k (check $ENV_FILE)"
  fi
}

verify_remote() {
  require_env "RCLONE_CONFIG_GDRIVE_TYPE"
  require_env "RCLONE_CONFIG_GDRIVE_SCOPE"
  require_env "RCLONE_CONFIG_GDRIVE_TOKEN"

  echo "🔍 Verifying rclone remote: gdrive"
  if ! rclone lsd gdrive: --config /dev/null >/dev/null 2>&1; then
    fatal "rclone verification failed. Run 'rclone lsd gdrive: --config /dev/null -vv' and check your RCLONE_CONFIG_GDRIVE_TOKEN in $ENV_FILE."
  fi
  echo "✅ rclone remote verified."
}

main() {
  ensure_rclone
  load_env_file
  verify_remote
}

main "$@"
