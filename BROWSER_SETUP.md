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

## Pixi (Windows / cross-platform)

If you’re not using Nix (e.g., on Windows), you can use Pixi to get a reproducible Python environment.

Install Pixi on Windows (one option):
```powershell
winget install --id PrefixDev.Pixi -e
```

### Windows PowerShell
```powershell
# From the repo root
pixi install

# Run the app
pixi run app

# Pass args to main.py after `--`
pixi run app -- -su laudboat -sb

# Delay app start by 5 minutes
pixi run app -- -su laudboat -sb -sd 5

# Optional: enter an activated shell
pixi shell --shell powershell
```

### Windows cmd.exe
```bat
pixi install
pixi run app
pixi run app -- -su laudboat -sb

REM Delay app start by 5 minutes
pixi run app -- -su laudboat -sb -sd 5
pixi shell --shell cmd
```

### Optional environment variables

If GeckoDriver/Firefox aren’t detected automatically on Windows, you can set:

- `GECKODRIVER_PATH` (path to `geckodriver.exe`)
- `FIREFOX_BIN` (path to `firefox.exe`)

### Note on Gmail / IMAP dependencies

The Gmail 2FA flow in [two_factor/gmail.py](two_factor/gmail.py) uses Python stdlib `imaplib` + `email`, so there’s no separate pip/conda package named “imap” or “gmail” to install.

On Windows, `zoneinfo.ZoneInfo` often needs timezone data; the Pixi env includes `tzdata` to cover that.

## Migration from Hardcoded Paths

**Before:**
```python
browser = BrowserFirefox(binary_path=r"C:\path\to\geckodriver.exe")
```

**After:**
```python
browser = create_browser()  # Auto-detects everything
```
