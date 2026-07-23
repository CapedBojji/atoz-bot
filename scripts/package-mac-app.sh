#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${PROJECT_DIR}/dist"
APP_PATH="${DIST_DIR}/AtoZ Bot.app"
ARCHIVE_PATH="${DIST_DIR}/AtoZ Bot.zip"

fail() {
  printf 'Could not package AtoZ Bot: %s\n' "$*" >&2
  exit 1
}

[ "$(uname -s)" = "Darwin" ] || fail "macOS is required to create the app archive"
[ -f "${PROJECT_DIR}/scripts/create-mac-app.sh" ] || fail "app builder is missing"

mkdir -p "${DIST_DIR}"
rm -rf "${APP_PATH}"
rm -f "${ARCHIVE_PATH}"

/bin/bash "${PROJECT_DIR}/scripts/create-mac-app.sh" \
  --project-dir "${PROJECT_DIR}" \
  --app-path "${APP_PATH}"

ditto -c -k --sequesterRsrc --keepParent "${APP_PATH}" "${ARCHIVE_PATH}"
printf 'Share this file: %s\n' "${ARCHIVE_PATH}"
