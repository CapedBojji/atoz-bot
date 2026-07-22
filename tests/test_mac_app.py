import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAC_APP_MODULE_PATH = PROJECT_ROOT / "scripts" / "mac-app.py"


def load_mac_app_module():
    spec = importlib.util.spec_from_file_location("atoz_mac_app", MAC_APP_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {MAC_APP_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mac_app = load_mac_app_module()


class MacAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def wait_until(self, predicate, timeout: float = 4.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for GUI process state")

    def make_project(self, temp_dir: str) -> Path:
        project = Path(temp_dir) / "atoz-bot"
        (project / "config").mkdir(parents=True)
        (project / "scripts").mkdir()
        (project / ".venv" / "bin").mkdir(parents=True)
        (project / "config" / "worker.toml").write_text("config")
        (project / "main.py").write_text("# test bot\n")
        (project / "scripts" / "config-builder.py").write_text("# builder\n")
        (project / "scripts" / "update-mac.sh").write_text("# updater\n")
        return project

    def test_bot_command_always_uses_manual_login_and_app_paths(self):
        project = Path("/Applications/Test AtoZ")

        arguments = mac_app.bot_arguments(project)

        self.assertEqual(arguments[0], str(project / "main.py"))
        self.assertIn("--manual_login", arguments)
        self.assertEqual(
            arguments[arguments.index("--config_dir") + 1],
            str(project / "config"),
        )
        self.assertEqual(
            arguments[arguments.index("--log_file") + 1],
            str(project / "app.log"),
        )

    def test_manual_login_prompt_detection_is_case_insensitive(self):
        self.assertTrue(
            mac_app.contains_manual_login_prompt(
                "Complete login, then PRESS ENTER HERE TO CONTINUE."
            )
        )
        self.assertTrue(
            mac_app.contains_manual_login_prompt(
                "Login cookies were not detected yet."
            )
        )
        self.assertFalse(mac_app.contains_manual_login_prompt("Bot is polling."))

    def test_bot_and_gui_share_running_event(self):
        main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn(mac_app.BOT_RUNNING_EVENT, main_source)

    def test_gui_start_continue_and_process_finish_handshake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(temp_dir)
            fake_python = project / ".venv" / "bin" / "python"
            fake_python.write_text(
                "#!/bin/bash\n"
                "printf 'Manual login required. press Enter here to continue.\\n'\n"
                "IFS= read -r reply\n"
                "printf 'BOT_CONTINUED\\n'\n"
                "printf 'ATOZ_EVENT:BOT_RUNNING\\n'\n"
                "sleep 0.2\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            window = mac_app.AtoZMacApp(
                project_root=project,
                mac_app_path=Path(temp_dir) / "AtoZ Bot.app",
            )

            window.start_bot()
            self.wait_until(lambda: window.continue_button.isEnabled())
            self.assertIn("Login waiting", window.status_label.text())

            window.continue_login()
            self.wait_until(
                lambda: window.status_label.text()
                == "Bot is running and watching for matching shifts."
            )
            self.assertFalse(window.continue_button.isEnabled())
            self.wait_until(lambda: not mac_app.process_running(window.bot_process))

            activity = window.output.toPlainText()
            self.assertIn("Continue sent after manual login", activity)
            self.assertIn("BOT_CONTINUED", activity)
            self.assertTrue(window.start_button.isEnabled())
            window.close()

    def test_close_stops_bot_waiting_for_continue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(temp_dir)
            fake_python = project / ".venv" / "bin" / "python"
            fake_python.write_text(
                "#!/bin/bash\n"
                "printf 'press Enter here to continue.\\n'\n"
                "IFS= read -r reply\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            window = mac_app.AtoZMacApp(project_root=project)

            window.start_bot()
            self.wait_until(lambda: window.continue_button.isEnabled())
            window.close()

            self.assertFalse(mac_app.process_running(window.bot_process))

    def test_update_button_runs_update_script_and_reports_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(temp_dir)
            update_script = project / "scripts" / "update-mac.sh"
            update_script.write_text(
                "#!/bin/bash\nprintf 'PULLED_LATEST_FROM_GITHUB\\n'\n",
                encoding="utf-8",
            )
            update_script.chmod(0o755)
            window = mac_app.AtoZMacApp(project_root=project)

            original_question = QMessageBox.question
            QMessageBox.question = lambda *args, **kwargs: (
                QMessageBox.StandardButton.Yes
            )
            try:
                window.update_app()
                self.wait_until(
                    lambda: not mac_app.process_running(window.update_process)
                    and "PULLED_LATEST_FROM_GITHUB" in window.output.toPlainText()
                )
            finally:
                QMessageBox.question = original_question

            self.assertIn("Update completed successfully", window.output.toPlainText())
            self.assertIn("Update installed", window.status_label.text())
            window.close()

    def test_dashboard_has_requested_controls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(temp_dir)
            window = mac_app.AtoZMacApp(project_root=project)

            self.assertEqual(window.start_button.text(), "Start App · Manual Login")
            self.assertEqual(window.continue_button.text(), "Continue After Login")
            self.assertEqual(window.update_button.text(), "Update from GitHub")
            self.assertEqual(window.close_button.text(), "Close App")
            window.close()


if __name__ == "__main__":
    unittest.main()
