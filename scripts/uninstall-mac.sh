#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${ATOZ_INSTALL_DIR:-${HOME}/atoz-bot}"
LAUNCHER_PATH="${ATOZ_LAUNCHER_PATH:-${HOME}/Desktop/Run AtoZ Bot.command}"
MAC_APP_PATH="${ATOZ_MAC_APP_PATH:-${HOME}/Applications/AtoZ Bot.app}"
MISE_BIN="${ATOZ_MISE_BIN:-${HOME}/.local/bin/mise}"
MISE_DATA_DIR="${ATOZ_MISE_DATA_DIR:-${HOME}/.local/share/mise}"
MISE_CACHE_DIR="${ATOZ_MISE_CACHE_DIR:-${HOME}/Library/Caches/mise}"
MANIFEST_PATH="${ATOZ_MANIFEST_PATH:-${HOME}/.atozbot-install-manifest}"
PYTHON_TOOL="python@3.12"
DRY_RUN="no"

trap 'printf "\nUninstall hit an error near line %s.\n" "$LINENO" >&2' ERR

info() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf '\nWarning: %s\n' "$*" >&2
}

fail() {
  printf '\nUninstall could not continue: %s\n' "$*" >&2
  exit 1
}

run() {
  local command="$1"
  printf '+ %s' "${command}"
  shift
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$@"
  fi
  if [ "${DRY_RUN}" = "yes" ]; then
    printf ' [dry run]\n'
    return 0
  fi
  printf '\n'
  "${command}" "$@"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN="yes"
        ;;
      -h|--help)
        printf 'Usage: %s [--dry-run]\n' "$0"
        exit 0
        ;;
      *)
        fail "unknown option: $1"
        ;;
    esac
    shift
  done
}

manifest_has() {
  local item="$1"
  [ -f "${MANIFEST_PATH}" ] && grep -Fqx "${item}" "${MANIFEST_PATH}"
}

unmark_installed() {
  local item="$1"
  local manifest_temp
  if [ "${DRY_RUN}" = "yes" ] || [ ! -f "${MANIFEST_PATH}" ]; then
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

confirm() {
  local prompt_text="$1"
  local default_value="$2"
  local reply

  read -r -p "${prompt_text} [${default_value}]: " reply
  reply="${reply:-$default_value}"
  case "${reply}" in
    yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

require_macos() {
  if [ "$(uname -s)" != "Darwin" ]; then
    fail "this uninstaller is only for macOS."
  fi
}

reject_broad_path() {
  local label="$1"
  local target="$2"
  case "${target}" in
    ""|/|"${HOME}"|"${HOME}/")
      fail "refusing unsafe ${label} path: ${target:-<empty>}"
      ;;
  esac
}

validate_paths() {
  if [ -z "${HOME:-}" ] || [ "${HOME}" = "/" ]; then
    fail "HOME is not a safe user folder."
  fi
  reject_broad_path "install" "${INSTALL_DIR}"
  reject_broad_path "launcher" "${LAUNCHER_PATH}"
  reject_broad_path "mac app" "${MAC_APP_PATH}"
  reject_broad_path "mise binary" "${MISE_BIN}"
  reject_broad_path "mise data" "${MISE_DATA_DIR}"
  reject_broad_path "mise cache" "${MISE_CACHE_DIR}"
  reject_broad_path "manifest" "${MANIFEST_PATH}"
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

remove_launcher() {
  local manifest_item="launcher:${LAUNCHER_PATH}"
  if [ -e "${LAUNCHER_PATH}" ]; then
    info "Removing desktop launcher."
    run rm -f "${LAUNCHER_PATH}"
    if [ "${DRY_RUN}" = "no" ] && [ ! -e "${LAUNCHER_PATH}" ]; then
      unmark_installed "${manifest_item}"
    fi
  else
    info "Desktop launcher was not found."
    unmark_installed "${manifest_item}"
  fi
}

remove_mac_application() {
  local manifest_item="mac-app:${MAC_APP_PATH}"
  if [ -e "${MAC_APP_PATH}" ]; then
    info "Removing AtoZ Bot.app."
    run rm -rf "${MAC_APP_PATH}"
    if [ "${DRY_RUN}" = "no" ] && [ ! -e "${MAC_APP_PATH}" ]; then
      unmark_installed "${manifest_item}"
    fi
  else
    info "AtoZ Bot.app was not found."
    unmark_installed "${manifest_item}"
  fi
}

remove_mise_python() {
  local manifest_item="mise-tool:${PYTHON_TOOL}"
  local default_answer="no"

  load_homebrew
  if ! command -v mise >/dev/null 2>&1; then
    info "mise is unavailable; skipping its Python runtime."
    return
  fi
  if ! mise where "${PYTHON_TOOL}" >/dev/null 2>&1; then
    info "mise ${PYTHON_TOOL} runtime was not found."
    unmark_installed "${manifest_item}"
    return
  fi

  if manifest_has "${manifest_item}"; then
    default_answer="yes"
  fi
  printf '\nThe app virtual environment is inside the project folder.\n'
  printf 'The separate mise Python runtime may be shared by other projects.\n'
  if confirm "Remove the mise ${PYTHON_TOOL} runtime?" "${default_answer}"; then
    if run mise uninstall -y "${PYTHON_TOOL}"; then
      if [ "${DRY_RUN}" = "no" ]; then
        unmark_installed "${manifest_item}"
      fi
    else
      warn "Could not uninstall mise ${PYTHON_TOOL}; its manifest entry was kept."
    fi
  else
    warn "Keeping mise ${PYTHON_TOOL}."
  fi
}

remove_mise_data() {
  if [ ! -e "${MISE_BIN}" ] && [ ! -d "${MISE_DATA_DIR}" ] && [ ! -d "${MISE_CACHE_DIR}" ]; then
    info "No user-level mise files or caches were found."
    return
  fi

  printf '\nRemaining mise files may be used by other projects.\n'
  if confirm "Remove user-level mise binary, tool data, and caches?" "no"; then
    if [ -e "${MISE_BIN}" ]; then
      run rm -f "${MISE_BIN}"
    fi
    if [ -d "${MISE_DATA_DIR}" ]; then
      run rm -rf "${MISE_DATA_DIR}"
    fi
    if [ -d "${MISE_CACHE_DIR}" ]; then
      run rm -rf "${MISE_CACHE_DIR}"
    fi
  else
    warn "Keeping user-level mise files and caches."
  fi
}

remove_homebrew_formula() {
  local formula="$1"
  local description="$2"
  local manifest_item="brew:${formula}"
  local default_answer="no"

  if ! brew list --formula "${formula}" >/dev/null 2>&1; then
    unmark_installed "${manifest_item}"
    return
  fi
  if manifest_has "${manifest_item}"; then
    default_answer="yes"
  fi
  if confirm "Uninstall ${description} from Homebrew?" "${default_answer}"; then
    if run brew uninstall "${formula}"; then
      if [ "${DRY_RUN}" = "no" ]; then
        unmark_installed "${manifest_item}"
      fi
    else
      warn "Could not uninstall ${formula}; its manifest entry was kept."
    fi
  else
    warn "Keeping Homebrew ${formula}."
  fi
}

remove_firefox() {
  local manifest_item="brew-cask:firefox"
  local default_answer="no"

  if ! brew list --cask firefox >/dev/null 2>&1; then
    unmark_installed "${manifest_item}"
    return
  fi
  if manifest_has "${manifest_item}"; then
    default_answer="yes"
  fi
  printf '\nFirefox may have existed before this bot setup.\n'
  if confirm "Uninstall Firefox Homebrew cask?" "${default_answer}"; then
    if run brew uninstall --cask firefox; then
      if [ "${DRY_RUN}" = "no" ]; then
        unmark_installed "${manifest_item}"
      fi
    else
      warn "Could not uninstall Firefox; its manifest entry was kept."
    fi
  else
    warn "Keeping Firefox."
  fi
}

remove_homebrew_packages() {
  load_homebrew
  if ! command -v brew >/dev/null 2>&1; then
    info "Homebrew was not found; skipping Homebrew packages."
    return
  fi

  remove_homebrew_formula "geckodriver" "geckodriver"

  printf '\nOnly remove mise if this setup installed it or you do not use it elsewhere.\n'
  remove_homebrew_formula "mise" "mise"

  printf '\ngit is commonly used by other tools. Only remove it if this setup installed it.\n'
  remove_homebrew_formula "git" "git"

  remove_firefox
  printf '\nHomebrew itself is not removed because other apps may depend on it.\n'
}

remove_project() {
  local manifest_item="project:${INSTALL_DIR}"
  if [ ! -e "${INSTALL_DIR}" ]; then
    info "Project folder was not found."
    unmark_installed "${manifest_item}"
    return
  fi

  printf '\nThis removes %s, including its private GUI library, .venv, logs, tokens, and config files.\n' "${INSTALL_DIR}"
  local default_answer="no"
  if manifest_has "${manifest_item}"; then
    default_answer="yes"
  fi
  if confirm "Remove the AtoZ Bot project folder?" "${default_answer}"; then
    run rm -rf "${INSTALL_DIR}"
    if [ "${DRY_RUN}" = "no" ] && [ ! -e "${INSTALL_DIR}" ]; then
      unmark_installed "${manifest_item}"
    fi
  else
    warn "Keeping ${INSTALL_DIR}."
  fi
}

finalize_manifest() {
  if [ "${DRY_RUN}" = "yes" ]; then
    info "Dry run complete. Nothing was removed."
    return
  fi
  if [ ! -f "${MANIFEST_PATH}" ]; then
    info "Uninstall complete. No setup-owned items remain tracked."
    return
  fi
  if [ ! -s "${MANIFEST_PATH}" ]; then
    rm -f "${MANIFEST_PATH}"
    info "Uninstall complete. No setup-owned items remain tracked."
    return
  fi

  warn "Uninstall finished with items kept or not removed. Tracking remains in ${MANIFEST_PATH}:"
  while IFS= read -r item; do
    [ -n "${item}" ] && printf '  - %s\n' "${item}" >&2
  done < "${MANIFEST_PATH}"
}

main() {
  parse_args "$@"
  require_macos
  validate_paths
  remove_mac_application
  remove_launcher
  remove_mise_python
  remove_mise_data
  remove_homebrew_packages
  remove_project
  finalize_manifest
}

main "$@"
