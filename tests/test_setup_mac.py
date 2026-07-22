import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup-mac.sh"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"


class MacSetupTests(unittest.TestCase):
    def test_gui_dependency_provides_widgets(self):
        from PySide6.QtWidgets import QApplication, QWidget

        self.assertIsNotNone(QApplication)
        self.assertIsNotNone(QWidget)

    def test_setup_script_has_valid_shell_syntax(self):
        subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], check=True)

    def test_setup_installs_and_checks_gui_dependency(self):
        setup_text = SETUP_SCRIPT.read_text(encoding="utf-8")
        requirements_text = REQUIREMENTS.read_text(encoding="utf-8")

        self.assertIn("PySide6", requirements_text)
        self.assertIn("pip install -r requirements.txt", setup_text)
        self.assertIn("import PySide6", setup_text)

    def test_setup_tracks_mac_app_and_mise_python_ownership(self):
        setup_text = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('mise where "${PYTHON_TOOL}"', setup_text)
        self.assertIn('mark_installed "mise-tool:${PYTHON_TOOL}"', setup_text)
        self.assertIn('mark_installed "mac-app:${MAC_APP_PATH}"', setup_text)

    def test_setup_builds_and_opens_mac_application(self):
        setup_text = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"${INSTALL_DIR}/scripts/create-mac-app.sh"', setup_text)
        self.assertIn('--project-dir "${INSTALL_DIR}"', setup_text)
        self.assertIn('--app-path "${MAC_APP_PATH}"', setup_text)
        self.assertIn('/usr/bin/open "${MAC_APP_PATH}"', setup_text)

    def test_setup_removes_only_manifest_owned_legacy_launcher(self):
        setup_text = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('grep -Fqx "${manifest_item}" "${MANIFEST_PATH}"', setup_text)
        self.assertIn('run rm -f "${LEGACY_LAUNCHER_PATH}"', setup_text)
        self.assertIn('unmark_installed "${manifest_item}"', setup_text)


if __name__ == "__main__":
    unittest.main()
