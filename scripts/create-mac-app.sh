#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${ATOZ_INSTALL_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
APP_PATH="${ATOZ_MAC_APP_PATH:-${HOME}/Applications/AtoZ Bot.app}"

fail() {
  printf 'Could not create AtoZ Bot.app: %s\n' "$*" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project-dir)
      [ "$#" -ge 2 ] || fail "--project-dir needs a path"
      PROJECT_DIR="$2"
      shift 2
      ;;
    --app-path)
      [ "$#" -ge 2 ] || fail "--app-path needs a path"
      APP_PATH="$2"
      shift 2
      ;;
    -h|--help)
      printf 'Usage: %s [--project-dir PATH] [--app-path PATH]\n' "$0"
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[ -f "${PROJECT_DIR}/main.py" ] || fail "main.py not found in ${PROJECT_DIR}"
[ -f "${PROJECT_DIR}/scripts/mac-app.py" ] || fail "scripts/mac-app.py not found"
[ -f "${PROJECT_DIR}/scripts/setup-mac.sh" ] || fail "scripts/setup-mac.sh not found"
[ -f "${PROJECT_DIR}/scripts/bootstrap-mac-app.sh" ] || fail "scripts/bootstrap-mac-app.sh not found"

CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
EXECUTABLE_PATH="${MACOS_DIR}/AtoZ Bot"
PAYLOAD_DIR="${RESOURCES_DIR}/project-template"

mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"

cat > "${CONTENTS_DIR}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>English</string>
  <key>CFBundleDisplayName</key>
  <string>AtoZ Bot</string>
  <key>CFBundleExecutable</key>
  <string>AtoZ Bot</string>
  <key>CFBundleIdentifier</key>
  <string>com.atozbot.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>AtoZ Bot</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cp "${PROJECT_DIR}/scripts/setup-mac.sh" "${RESOURCES_DIR}/setup-mac.sh"
chmod 755 "${RESOURCES_DIR}/setup-mac.sh"
cp "${PROJECT_DIR}/scripts/bootstrap-mac-app.sh" "${RESOURCES_DIR}/bootstrap-mac-app.sh"
chmod 755 "${RESOURCES_DIR}/bootstrap-mac-app.sh"
mkdir -p "${PAYLOAD_DIR}"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '.devenv' \
  --exclude '__pycache__' \
  --exclude 'config' \
  --exclude 'app.log' \
  --exclude '.env' \
  --exclude 'dist' \
  --exclude 'build' \
  "${PROJECT_DIR}/" "${PAYLOAD_DIR}/"

{
  printf '#!/usr/bin/env bash\n'
  printf 'set -Eeuo pipefail\n'
  cat <<'LAUNCHER'

APP_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -x "/opt/homebrew/bin/brew" ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x "/usr/local/bin/brew" ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

INSTALL_DIR="${HOME}/atoz-bot"
PYTHON_PATH="${INSTALL_DIR}/.venv/bin/python"
GUI_PATH="${INSTALL_DIR}/scripts/mac-app.py"
BOOTSTRAP_PATH="${APP_PATH}/Contents/Resources/bootstrap-mac-app.sh"
PAYLOAD_DIR="${APP_PATH}/Contents/Resources/project-template"
LOG_DIR="${HOME}/Library/Logs"
LAUNCH_LOG="${LOG_DIR}/AtoZ Bot Launcher.log"

mkdir -p "${LOG_DIR}"
if [ ! -x "${PYTHON_PATH}" ] || [ ! -f "${GUI_PATH}" ]; then
  printf -v setup_command '/bin/bash %q --payload %q --install-dir %q' \
    "${BOOTSTRAP_PATH}" "${PAYLOAD_DIR}" "${INSTALL_DIR}"
  escaped_setup_command="${setup_command//\\/\\\\}"
  escaped_setup_command="${escaped_setup_command//\"/\\\"}"
  /usr/bin/osascript \
    -e 'tell application "Terminal" to activate' \
    -e "tell application \"Terminal\" to do script \"${escaped_setup_command}\"" || true
  exit 1
fi

export ATOZ_INSTALL_DIR="${INSTALL_DIR}"
export ATOZ_MAC_APP_PATH="${APP_PATH}"
cd "${INSTALL_DIR}"
exec "${PYTHON_PATH}" "${GUI_PATH}" >> "${LAUNCH_LOG}" 2>&1
LAUNCHER
} > "${EXECUTABLE_PATH}"

chmod 755 "${EXECUTABLE_PATH}"
touch "${APP_PATH}"
printf 'Created %s\n' "${APP_PATH}"
