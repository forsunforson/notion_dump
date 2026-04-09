#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${1:-$(whoami)}"
SERVICE_NAME="${2:-chronofold-bot}"
SUDOERS_FILE="/etc/sudoers.d/${SERVICE_NAME}"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "❌ systemctl not found. This script only supports Linux systems with systemd."
    exit 1
fi

if ! command -v visudo >/dev/null 2>&1; then
    echo "❌ visudo not found. Please install sudo/visudo before running this script."
    exit 1
fi

SYSTEMCTL_BIN="$(command -v systemctl)"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<EOF
${TARGET_USER} ALL=NOPASSWD: ${SYSTEMCTL_BIN} restart ${SERVICE_NAME}, ${SYSTEMCTL_BIN} status ${SERVICE_NAME}
Defaults:${TARGET_USER} !requiretty
EOF

echo "📝 Generated sudoers config:"
cat "$TMP_FILE"
echo

echo "🔍 Validating sudoers syntax..."
sudo visudo -c -f "$TMP_FILE"

echo "🚀 Installing to ${SUDOERS_FILE} ..."
sudo install -m 440 "$TMP_FILE" "$SUDOERS_FILE"

echo "✅ Done."
echo "You can verify with:"
echo "  sudo -n ${SYSTEMCTL_BIN} restart ${SERVICE_NAME}"
echo "  sudo -n ${SYSTEMCTL_BIN} status ${SERVICE_NAME} --no-pager"
