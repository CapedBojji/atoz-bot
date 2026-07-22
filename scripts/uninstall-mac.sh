#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${HOME}/atoz-bot"
LAUNCHER_PATH="${HOME}/Desktop/Run AtoZ Bot.command"
MISE_BIN="${HOME}/.local/bin/mise"
MANIFEST_PATH="${HOME}/.atozbot-install-manifest"

trap 'printf "\nUninstall hit an error near line %s.\n" "$LINENO" >&2' ERR

info() {
  printf '\n==> %s\n' "$*"
}

warn() {
  printf '\nWarning: %s\n' "$*" >&2
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

manifest_has() {
  local item="$1"
  [ -f "${MANIFEST_PATH}" ] && grep -qx "${item}" "${MANIFEST_PATH}"
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
    printf 'This uninstaller is only for macOS.\n' >&2
    exit 1
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

remove_launcher() {
  if [ -e "${LAUNCHER_PATH}" ]; then
    info "Removing desktop launcher."
    run rm -f "${LAUNCHER_PATH}"
  else
    info "Desktop launcher was not found."
  fi
}

remove_project() {
  if [ ! -e "${INSTALL_DIR}" ]; then
    info "Project folder was not found."
    return
  fi

  printf '\nThis will remove %s, including .venv and config files created there.\n' "${INSTALL_DIR}"
  local default_answer="no"
  if manifest_has "project:${INSTALL_DIR}"; then
    default_answer="yes"
  fi
  if confirm "Remove the AtoZ Bot project folder?" "${default_answer}"; then
    run rm -rf "${INSTALL_DIR}"
  else
    warn "Keeping ${INSTALL_DIR}."
  fi
}

remove_homebrew_packages() {
  load_homebrew
  if ! command -v brew >/dev/null 2>&1; then
    info "Homebrew was not found; skipping Homebrew packages."
    return
  fi

  if brew list --formula geckodriver >/dev/null 2>&1; then
    local geckodriver_default="no"
    if manifest_has "brew:geckodriver"; then
      geckodriver_default="yes"
    fi
    if confirm "Uninstall geckodriver from Homebrew?" "${geckodriver_default}"; then
      run brew uninstall geckodriver || warn "Could not uninstall geckodriver."
    fi
  fi

  if brew list --formula mise >/dev/null 2>&1; then
    local mise_default="no"
    if manifest_has "brew:mise"; then
      mise_default="yes"
    fi
    printf '\nOnly remove Homebrew mise if this setup installed it or you do not use it elsewhere.\n'
    if confirm "Uninstall the Homebrew mise formula?" "${mise_default}"; then
      run brew uninstall mise || warn "Could not uninstall Homebrew mise."
    fi
  fi

  if brew list --formula git >/dev/null 2>&1; then
    local git_default="no"
    if manifest_has "brew:git"; then
      git_default="yes"
    fi
    printf '\ngit is commonly used by other tools. Only remove it if this setup installed it.\n'
    if confirm "Uninstall the Homebrew git formula?" "${git_default}"; then
      run brew uninstall git || warn "Could not uninstall Homebrew git."
    else
      warn "Keeping Homebrew git."
    fi
  fi

  if brew list --cask firefox >/dev/null 2>&1; then
    local firefox_default="no"
    if manifest_has "brew-cask:firefox"; then
      firefox_default="yes"
    fi
    printf '\nFirefox may have existed before this bot setup.\n'
    if confirm "Uninstall Firefox Homebrew cask?" "${firefox_default}"; then
      run brew uninstall --cask firefox || warn "Could not uninstall Firefox."
    else
      warn "Keeping Firefox."
    fi
  fi

  printf '\nHomebrew itself is not removed because other apps may depend on it.\n'
}

remove_mise() {
  if [ ! -x "${MISE_BIN}" ]; then
    info "mise installed by the setup script was not found at ${MISE_BIN}."
    return
  fi

  printf '\nmise may be used by other projects on this Mac.\n'
  if confirm "Remove user-level mise binary and its downloaded tool data?" "no"; then
    run rm -f "${MISE_BIN}"
    if [ -d "${HOME}/.local/share/mise" ]; then
      run rm -rf "${HOME}/.local/share/mise"
    fi
    if [ -d "${HOME}/Library/Caches/mise" ]; then
      run rm -rf "${HOME}/Library/Caches/mise"
    fi
  else
    warn "Keeping mise."
  fi
}

main() {
  require_macos
  remove_launcher
  remove_project
  remove_homebrew_packages
  remove_mise
  if [ -f "${MANIFEST_PATH}" ]; then
    run rm -f "${MANIFEST_PATH}"
  fi

  info "Uninstall complete."
}

main "$@"
