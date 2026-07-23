#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/CapedBojji/atoz-bot.git"
ARCHIVE_URL="https://github.com/CapedBojji/atoz-bot/archive/refs/heads/main.zip"
INSTALL_DIR="${ATOZ_INSTALL_DIR:-${HOME}/atoz-bot}"
MAC_APP_PATH="${HOME}/Applications/AtoZ Bot.app"
LEGACY_LAUNCHER_PATH="${HOME}/Desktop/Run AtoZ Bot.command"
PYTHON_TOOL="python@3.12"
MANIFEST_PATH="${HOME}/.atozbot-install-manifest"

trap 'printf "\nSetup hit an error near line %s. You can re-run this installer after fixing the issue.\n" "$LINENO" >&2' ERR

info() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf '\nWarning: %s\n' "$*" >&2
}

fail() {
  printf '\nSetup could not continue: %s\n' "$*" >&2
  printf 'You can re-run this installer after fixing the issue.\n' >&2
  exit 1
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

command_works() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 && "${command_name}" --version >/dev/null 2>&1
}

mark_installed() {
  local item="$1"
  mkdir -p "$(dirname "${MANIFEST_PATH}")"
  touch "${MANIFEST_PATH}"
  if ! grep -qx "${item}" "${MANIFEST_PATH}"; then
    printf '%s\n' "${item}" >> "${MANIFEST_PATH}"
  fi
}

unmark_installed() {
  local item="$1"
  local manifest_temp
  if [ ! -f "${MANIFEST_PATH}" ]; then
    return
  fi
  manifest_temp="${MANIFEST_PATH}.tmp.$$"
  grep -Fvx "${item}" "${MANIFEST_PATH}" > "${manifest_temp}" || true
  if [ -s "${manifest_temp}" ]; then
    mv "${manifest_temp}" "${MANIFEST_PATH}"
  else
    rm -f "${manifest_temp}" "${MANIFEST_PATH}"
  fi
}

require_macos() {
  if [ "$(uname -s)" != "Darwin" ]; then
    fail "this installer is only for macOS."
  fi
}

load_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi

  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

install_homebrew_if_needed() {
  load_homebrew
  if command -v brew >/dev/null 2>&1; then
    info "Homebrew is already installed."
    return
  fi

  info "Installing Homebrew. macOS may ask for the computer password."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  load_homebrew
  if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew installed, but the brew command is not available yet. Open a new Terminal window and re-run this script."
  fi
}

install_brew_packages() {
  info "Checking required tools."
  run brew update

  if command_works git; then
    info "git is already available."
  else
    info "Installing git."
    run brew install git
    mark_installed "brew:git"
  fi

  if [ -x "${HOME}/.local/bin/mise" ]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  fi

  if command_works mise; then
    info "mise is already available."
  else
    info "Installing mise."
    run brew install mise
    mark_installed "brew:mise"
  fi

  if command_works geckodriver; then
    info "geckodriver is already available."
  else
    info "Installing geckodriver."
    run brew install geckodriver
    mark_installed "brew:geckodriver"
  fi

  if [ -d "/Applications/Firefox.app" ] || [ -d "${HOME}/Applications/Firefox.app" ]; then
    info "Firefox is already installed."
  else
    info "Installing Firefox."
    run brew install --cask firefox
    mark_installed "brew-cask:firefox"
  fi
}

download_repo_archive() {
  local temp_dir
  local archive_path
  local extracted_dir

  temp_dir="$(mktemp -d)"
  archive_path="${temp_dir}/atoz-bot.zip"

  run curl -fL "${ARCHIVE_URL}" -o "${archive_path}"
  run ditto -x -k "${archive_path}" "${temp_dir}"
  extracted_dir="$(find "${temp_dir}" -maxdepth 1 -type d -name 'atoz-bot-*' | head -n 1)"
  if [ -z "${extracted_dir}" ]; then
    rm -rf "${temp_dir}"
    fail "could not unpack the AtoZ Bot download."
  fi

  mkdir -p "${INSTALL_DIR}"
  run rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'config' \
    --exclude 'app.log' \
    --exclude '.env' \
    "${extracted_dir}/" "${INSTALL_DIR}/"

  rm -rf "${temp_dir}"
}

clone_or_update_repo() {
  info "Preparing AtoZ Bot in ${INSTALL_DIR}."

  if [ "${ATOZ_SKIP_REPO_SYNC:-no}" = "yes" ]; then
    [ -f "${INSTALL_DIR}/main.py" ] || fail "bundled app files are missing main.py"
    mark_installed "project:${INSTALL_DIR}"
    info "Using bundled app files for first-run setup."
    return
  fi

  if [ -d "${INSTALL_DIR}/.git" ]; then
    run git -C "${INSTALL_DIR}" remote set-url origin "${REPO_URL}"
    run git -C "${INSTALL_DIR}" fetch origin
    run git -C "${INSTALL_DIR}" pull --ff-only
    return
  fi

  if [ ! -e "${INSTALL_DIR}" ]; then
    run git clone "${REPO_URL}" "${INSTALL_DIR}"
    mark_installed "project:${INSTALL_DIR}"
    return
  fi

  if [ ! -f "${INSTALL_DIR}/main.py" ]; then
    fail "${INSTALL_DIR} already exists but does not look like AtoZ Bot. Move it aside and re-run this script."
  fi

  info "Updating non-git install at ${INSTALL_DIR} from a GitHub zip download."
  download_repo_archive
}

install_python_environment() {
  info "Installing Python 3.12 with mise."
  cd "${INSTALL_DIR}"

  local python_already_installed="no"
  if mise where "${PYTHON_TOOL}" >/dev/null 2>&1; then
    python_already_installed="yes"
  fi

  run mise install -y "${PYTHON_TOOL}"
  if [ "${python_already_installed}" = "no" ]; then
    mark_installed "mise-tool:${PYTHON_TOOL}"
  fi
  run mise exec -y "${PYTHON_TOOL}" -- python -m venv .venv
  run .venv/bin/python -m pip install --upgrade pip setuptools wheel
  run .venv/bin/python -m pip install -r requirements.txt
  run .venv/bin/python -c 'import PySide6; print("Config builder GUI ready.")'
}

create_mac_application() {
  info "Creating AtoZ Bot.app."
  mkdir -p "${INSTALL_DIR}/config"
  run /bin/bash "${INSTALL_DIR}/scripts/create-mac-app.sh" \
    --project-dir "${INSTALL_DIR}" \
    --app-path "${MAC_APP_PATH}"
  mark_installed "mac-app:${MAC_APP_PATH}"
}

migrate_legacy_launcher() {
  local manifest_item="launcher:${LEGACY_LAUNCHER_PATH}"
  if [ -e "${LEGACY_LAUNCHER_PATH}" ] \
    && [ -f "${MANIFEST_PATH}" ] \
    && grep -Fqx "${manifest_item}" "${MANIFEST_PATH}"; then
    info "Removing old desktop command launcher."
    run rm -f "${LEGACY_LAUNCHER_PATH}"
    unmark_installed "${manifest_item}"
  fi
}

open_mac_application() {
  info "Opening AtoZ Bot."
  run /usr/bin/open "${MAC_APP_PATH}"
}

main() {
  require_macos
  install_homebrew_if_needed
  install_brew_packages
  clone_or_update_repo
  install_python_environment
  create_mac_application
  migrate_legacy_launcher
  open_mac_application

  info "Setup complete."
  printf 'To run the bot later, open: %s\n' "${MAC_APP_PATH}"
  printf 'To uninstall later, run: %s/scripts/uninstall-mac.sh\n' "${INSTALL_DIR}"
  printf 'To preview cleanup first, run: %s/scripts/uninstall-mac.sh --dry-run\n' "${INSTALL_DIR}"
}

main "$@"
