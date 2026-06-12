#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/CapedBojji/atoz-bot.git"
INSTALL_DIR="${HOME}/atoz-bot"
LAUNCHER_PATH="${HOME}/Desktop/Run AtoZ Bot.command"
PYTHON_TOOL="python@3.12"

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
  info "Installing command line tools with Homebrew."
  run brew update
  run brew install git mise geckodriver

  info "Installing Firefox with Homebrew."
  run brew install --cask firefox || warn "Firefox may already be installed. Continuing."
}

clone_or_update_repo() {
  info "Preparing AtoZ Bot in ${INSTALL_DIR}."

  if [ -d "${INSTALL_DIR}/.git" ]; then
    run git -C "${INSTALL_DIR}" remote set-url origin "${REPO_URL}"
    run git -C "${INSTALL_DIR}" fetch origin
    run git -C "${INSTALL_DIR}" pull --ff-only
    return
  fi

  if [ -e "${INSTALL_DIR}" ]; then
    fail "${INSTALL_DIR} already exists but is not a git checkout. Move it aside and re-run this script."
  fi

  run git clone "${REPO_URL}" "${INSTALL_DIR}"
}

install_python_environment() {
  info "Installing Python 3.12 with mise."
  cd "${INSTALL_DIR}"

  run mise install -y "${PYTHON_TOOL}"
  run mise exec -y "${PYTHON_TOOL}" -- python -m venv .venv
  run .venv/bin/python -m pip install --upgrade pip setuptools wheel
  run .venv/bin/python -m pip install -r requirements.txt
}

prompt_default() {
  local prompt_text="$1"
  local default_value="$2"
  local reply

  if [ -n "${default_value}" ]; then
    read -r -p "${prompt_text} [${default_value}]: " reply
    printf '%s' "${reply:-$default_value}"
  else
    read -r -p "${prompt_text}: " reply
    printf '%s' "${reply}"
  fi
}

prompt_required() {
  local prompt_text="$1"
  local reply

  while true; do
    reply="$(prompt_default "${prompt_text}" "")"
    if [ -n "${reply}" ]; then
      printf '%s' "${reply}"
      return
    fi
    printf 'Please enter a value.\n'
  done
}

toml_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "${value}"
}

sanitize_config_name() {
  local value="$1"
  value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]_-')"
  if [ -z "${value}" ]; then
    value="friend"
  fi
  printf '%s' "${value}"
}

create_interactive_config() {
  info "Creating a bot config."
  mkdir -p "${INSTALL_DIR}/config"

  local raw_name
  local config_name
  local config_file
  raw_name="$(prompt_default "Config name, used for the file name" "friend")"
  config_name="$(sanitize_config_name "${raw_name}")"
  config_file="${INSTALL_DIR}/config/${config_name}.toml"

  if [ -f "${config_file}" ]; then
    local overwrite
    overwrite="$(prompt_default "${config_file} already exists. Overwrite it? Type yes or no" "no")"
    case "${overwrite}" in
      yes|YES|y|Y) ;;
      *)
        info "Keeping existing config at ${config_file}."
        return
        ;;
    esac
  fi

  local time_zone
  local pick_start
  local job_name
  local duration
  time_zone="$(prompt_default "Timezone" "America/New_York")"
  job_name="$(prompt_default "Job name" "Default shift search")"
  pick_start="$(prompt_default "When should picking start? Leave blank for immediate" "")"
  duration="$(prompt_default "How long should this job run once started? Use minutes or HH:MM" "60")"

  local starts=()
  local ends=()
  local add_more="yes"
  local start_window
  local end_window

  while true; do
    start_window="$(prompt_required "Desired shift window start, for example sunday at 6:00 AM")"
    end_window="$(prompt_required "Desired shift window end, for example sunday at 6:15 PM")"
    starts+=("${start_window}")
    ends+=("${end_window}")

    add_more="$(prompt_default "Add another desired shift window? Type yes or no" "no")"
    case "${add_more}" in
      yes|YES|y|Y) ;;
      *) break ;;
    esac
  done

  {
    printf '# Generated by scripts/setup-mac.sh\n'
    printf 'manual_login = true\n\n'
    printf '[[jobs]]\n'
    printf 'name = "%s"\n' "$(toml_escape "${job_name}")"
    printf 'time_zone = "%s"\n' "$(toml_escape "${time_zone}")"
    printf 'duration = "%s"\n' "$(toml_escape "${duration}")"
    if [ -n "${pick_start}" ]; then
      printf 'time_to_pick = "%s"\n' "$(toml_escape "${pick_start}")"
    fi
    printf '\n'

    local index
    index=0
    while [ "${index}" -lt "${#starts[@]}" ]; do
      printf '[[jobs.rules]]\n'
      printf 'start = "%s"\n' "$(toml_escape "${starts[$index]}")"
      printf 'end = "%s"\n' "$(toml_escape "${ends[$index]}")"
      printf 'priority = 0\n\n'
      index=$((index + 1))
    done
  } > "${config_file}"

  chmod 600 "${config_file}"
  info "Wrote ${config_file}."
}

create_launcher() {
  info "Creating desktop launcher."
  mkdir -p "${HOME}/Desktop"

  cat > "${LAUNCHER_PATH}" <<'LAUNCHER'
#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${HOME}/atoz-bot"

if [ -x "/opt/homebrew/bin/brew" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x "/usr/local/bin/brew" ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

cd "${PROJECT_DIR}"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python environment is missing. Run setup-mac.sh again."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is missing from PATH. Run setup-mac.sh again."
  read -r -p "Press Enter to close..."
  exit 1
fi

export GECKODRIVER_PATH="$(brew --prefix)/bin/geckodriver"
if [ -x "/Applications/Firefox.app/Contents/MacOS/firefox" ]; then
  export FIREFOX_BIN="/Applications/Firefox.app/Contents/MacOS/firefox"
fi

set +e
".venv/bin/python" main.py --manual_login --config_dir config
status=$?
set -e

if [ "${status}" -ne 0 ]; then
  echo
  echo "AtoZ Bot stopped with an error."
  read -r -p "Press Enter to close..."
fi

exit "${status}"
LAUNCHER

  chmod +x "${LAUNCHER_PATH}"
  info "Created ${LAUNCHER_PATH}."
}

main() {
  require_macos
  install_homebrew_if_needed
  install_brew_packages
  clone_or_update_repo
  install_python_environment
  create_interactive_config
  create_launcher

  info "Setup complete."
  printf 'To run the bot later, double-click: %s\n' "${LAUNCHER_PATH}"
}

main "$@"
