#!/usr/bin/env bash
set -Eeuo pipefail

PAYLOAD_DIR=""
INSTALL_DIR="${HOME}/atoz-bot"

fail() {
  printf 'AtoZ Bot first-run setup could not continue: %s\n' "$*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --payload)
      [ "$#" -ge 2 ] || fail "--payload needs a path"
      PAYLOAD_DIR="$2"
      shift 2
      ;;
    --install-dir)
      [ "$#" -ge 2 ] || fail "--install-dir needs a path"
      INSTALL_DIR="$2"
      shift 2
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[ -n "${PAYLOAD_DIR}" ] || fail "no bundled project payload was provided"
[ -f "${PAYLOAD_DIR}/main.py" ] || fail "bundled project payload is incomplete"
[ -f "${PAYLOAD_DIR}/scripts/setup-mac.sh" ] || fail "bundled setup script is missing"
[ -n "${HOME:-}" ] || fail "HOME is not set"
[ "${INSTALL_DIR}" != "/" ] && [ "${INSTALL_DIR}" != "${HOME}" ] || fail "unsafe install path: ${INSTALL_DIR}"

printf 'Installing bundled AtoZ Bot files in %s\n' "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

# Keep the user's bot configuration, tokens, logs, and private environment when
# repairing an existing installation. The payload contains only app source.
rsync -a --delete \
  --exclude '.venv' \
  --exclude '.devenv' \
  --exclude '__pycache__' \
  --exclude 'config' \
  --exclude 'app.log' \
  --exclude '.env' \
  "${PAYLOAD_DIR}/" "${INSTALL_DIR}/"

exec env \
  ATOZ_INSTALL_DIR="${INSTALL_DIR}" \
  ATOZ_SKIP_REPO_SYNC=yes \
  /bin/bash "${INSTALL_DIR}/scripts/setup-mac.sh"
