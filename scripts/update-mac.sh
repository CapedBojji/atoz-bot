#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/CapedBojji/atoz-bot.git"
BRANCH="main"
INSTALL_DIR="${ATOZ_INSTALL_DIR:-${HOME}/atoz-bot}"
APP_PATH="${ATOZ_MAC_APP_PATH:-${HOME}/Applications/AtoZ Bot.app}"

info() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf '\nUpdate could not continue: %s\n' "$*" >&2
  exit 1
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

if [ "$(uname -s)" != "Darwin" ]; then
  fail "this updater is only for macOS."
fi
if [ -z "${HOME:-}" ] || [ "${INSTALL_DIR}" = "/" ] || [ "${INSTALL_DIR}" = "${HOME}" ]; then
  fail "unsafe install path: ${INSTALL_DIR}"
fi
if [ ! -d "${INSTALL_DIR}/.git" ]; then
  fail "${INSTALL_DIR} is not a git checkout. Re-run setup-mac.sh to repair it."
fi
if [ ! -x "${INSTALL_DIR}/.venv/bin/python" ]; then
  fail "the app Python environment is missing. Re-run setup-mac.sh."
fi

if [ -x "/opt/homebrew/bin/brew" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x "/usr/local/bin/brew" ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

tracked_changes="$(git -C "${INSTALL_DIR}" status --porcelain --untracked-files=no)"
if [ -n "${tracked_changes}" ]; then
  printf '%s\n' "${tracked_changes}" >&2
  fail "tracked project files have local changes. Commit or restore them before updating."
fi

info "Pulling latest ${BRANCH} from GitHub."
run git -C "${INSTALL_DIR}" remote set-url origin "${REPO_URL}"
run git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"

info "Refreshing private app dependencies."
run "${INSTALL_DIR}/.venv/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt"
run "${INSTALL_DIR}/.venv/bin/python" -m pip check

info "Refreshing macOS application bundle."
run /bin/bash "${INSTALL_DIR}/scripts/create-mac-app.sh" \
  --project-dir "${INSTALL_DIR}" \
  --app-path "${APP_PATH}"

revision="$(git -C "${INSTALL_DIR}" rev-parse --short HEAD)"
info "Update complete at revision ${revision}."
