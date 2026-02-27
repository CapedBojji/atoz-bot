# GeckoDriver Setup with devenv

## Overview

This project now automatically manages GeckoDriver and Firefox through the Nix devenv setup, eliminating the need for manual driver installation or hardcoded paths.

## How It Works

### 1. Automatic Driver Detection

The `BrowserFirefox` class now automatically finds GeckoDriver in this order:

1. **Environment variable**: `GECKODRIVER_PATH` if set
2. **System PATH**: Uses `shutil.which('geckodriver')` 
3. **webdriver-manager**: Downloads and manages driver automatically
4. **Selenium built-in**: Falls back to Selenium's driver manager

### 2. Nix Integration

The `flake.nix` includes:
- `pkgs.geckodriver` - GeckoDriver binary
- `pkgs.firefox` - Firefox browser

### 3. Usage Examples

#### Simple Usage
```python
from utils.browser import create_browser

# Create browser with auto-detected GeckoDriver
browser = create_browser(headless=True)
browser.start()
browser.get_url("https://example.com")
browser.stop()
```

#### Advanced Usage
```python
from utils.browser import BrowserFirefox
from selenium.webdriver.firefox.options import Options as FirefoxOptions

options = FirefoxOptions()
options.add_argument("--headless")

browser = BrowserFirefox(options=options)
print(f"Using GeckoDriver at: {browser.gecko_driver_path}")
browser.start()
# ... your automation code
browser.stop()
```

## Environment Setup

### Initial Setup
```bash
# Reload devenv to get GeckoDriver and Firefox
direnv reload

# Verify installation
which geckodriver
geckodriver --version
```

### Environment Variables (Optional)

If you need to use a specific GeckoDriver:
```bash
export GECKODRIVER_PATH="/path/to/your/geckodriver"
```

## Dependencies

- **selenium**: Web automation framework
- **webdriver-manager**: Automatic driver management (fallback)
- **geckodriver**: Firefox WebDriver (via Nix)
- **firefox**: Firefox browser (via Nix)

## Benefits

1. **Cross-platform**: Works on any system with Nix
2. **Version controlled**: GeckoDriver version is locked in flake.nix
3. **No manual downloads**: Everything is managed automatically
4. **Reproducible**: Same versions across all environments
5. **Clean**: No hardcoded paths or system dependencies

## Troubleshooting

### GeckoDriver Not Found
```bash
# Check if GeckoDriver is in PATH
which geckodriver

# Reload devenv if needed
direnv reload
```

### Firefox Not Found
```bash
# Check Firefox location
which firefox

# On macOS, Firefox might be in /Applications
# The code will handle this automatically
```

### WebDriver Manager Issues
```bash
# Install webdriver-manager for automatic fallback
pip install webdriver-manager
```

## Mise (Windows / cross-platform)

If you’re not using Nix (e.g., on Windows), you can use Mise to manage Python and project tasks.

Install Mise on Windows (one option):
```powershell
winget install --id jdx.mise -e
```

### Windows PowerShell
```powershell
# From the repo root
mise install

# Install dependencies
mise run install

# Run the app
mise run app

# Pass args to main.py after `--`
mise run app -- -su laudboat -sb

# Delay app start by 5 minutes
mise run app -- -su laudboat -sb -sd 5

# Optional: enter an activated shell
mise shell
```

### Windows cmd.exe
```bat
mise install
mise run install
mise run app
mise run app -- -su laudboat -sb

REM Delay app start by 5 minutes
mise run app -- -su laudboat -sb -sd 5
mise shell
```

### Optional environment variables

If GeckoDriver/Firefox aren’t detected automatically on Windows, you can set:

- `GECKODRIVER_PATH` (path to `geckodriver.exe`)
- `FIREFOX_BIN` (path to `firefox.exe`)

### Note on Gmail / IMAP dependencies

The Gmail 2FA flow in [two_factor/gmail.py](two_factor/gmail.py) uses Python stdlib `imaplib` + `email`, so there’s no separate pip package named “imap” or “gmail” to install.

On Windows, `zoneinfo.ZoneInfo` often needs timezone data; `tzdata` is included in [requirements.txt](requirements.txt).

## Migration from Hardcoded Paths

**Before:**
```python
browser = BrowserFirefox(binary_path=r"C:\path\to\geckodriver.exe")
```

**After:**
```python
browser = create_browser()  # Auto-detects everything
```
