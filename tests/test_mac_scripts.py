import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREATE_APP_SCRIPT = PROJECT_ROOT / "scripts" / "create-mac-app.sh"
BOOTSTRAP_APP_SCRIPT = PROJECT_ROOT / "scripts" / "bootstrap-mac-app.sh"
PACKAGE_APP_SCRIPT = PROJECT_ROOT / "scripts" / "package-mac-app.sh"
UPDATE_SCRIPT = PROJECT_ROOT / "scripts" / "update-mac.sh"


class MacScriptTests(unittest.TestCase):
    def make_command(self, bin_dir: Path, name: str, body: str) -> Path:
        command = bin_dir / name
        command.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        command.chmod(0o755)
        return command

    def test_app_bundle_contains_valid_plist_and_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "atoz-bot"
            app_path = Path(temp_dir) / "Applications" / "AtoZ Bot.app"
            (project / "scripts").mkdir(parents=True)
            (project / "main.py").write_text("# main\n", encoding="utf-8")
            (project / "scripts" / "mac-app.py").write_text(
                "# gui\n", encoding="utf-8"
            )
            (project / "scripts" / "setup-mac.sh").write_text(
                "#!/bin/bash\n", encoding="utf-8"
            )
            (project / "scripts" / "bootstrap-mac-app.sh").write_text(
                "#!/bin/bash\n", encoding="utf-8"
            )

            subprocess.run(
                [
                    "/bin/bash",
                    str(CREATE_APP_SCRIPT),
                    "--project-dir",
                    str(project),
                    "--app-path",
                    str(app_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            plist_path = app_path / "Contents" / "Info.plist"
            executable = app_path / "Contents" / "MacOS" / "AtoZ Bot"
            bundled_setup = app_path / "Contents" / "Resources" / "setup-mac.sh"
            bundled_bootstrap = (
                app_path / "Contents" / "Resources" / "bootstrap-mac-app.sh"
            )
            payload_main = app_path / "Contents" / "Resources" / "project-template" / "main.py"
            with plist_path.open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            launcher = executable.read_text(encoding="utf-8")

            self.assertEqual(plist["CFBundleIdentifier"], "com.atozbot.launcher")
            self.assertEqual(plist["CFBundleExecutable"], "AtoZ Bot")
            self.assertTrue(os.access(executable, os.X_OK))
            self.assertTrue(os.access(bundled_setup, os.X_OK))
            self.assertTrue(os.access(bundled_bootstrap, os.X_OK))
            self.assertTrue(payload_main.is_file())
            self.assertIn('exec "${PYTHON_PATH}" "${GUI_PATH}"', launcher)
            self.assertIn('application "Terminal"', launcher)
            self.assertIn('project-template', launcher)
            self.assertIn('INSTALL_DIR="${HOME}/atoz-bot"', launcher)
            self.assertIn(
                'APP_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"',
                launcher,
            )

    def make_update_install(
        self, temp_dir: str
    ) -> tuple[Path, Path, dict[str, str], Path, Path, Path]:
        root = Path(temp_dir)
        fake_home = root / "home"
        fake_bin = root / "bin"
        install_dir = root / "atoz-bot"
        app_path = fake_home / "Applications" / "AtoZ Bot.app"
        git_log = root / "git.log"
        python_log = root / "python.log"
        app_log = root / "app-builder.log"

        fake_home.mkdir()
        fake_bin.mkdir()
        (install_dir / ".git").mkdir(parents=True)
        (install_dir / ".venv" / "bin").mkdir(parents=True)
        (install_dir / "scripts").mkdir()
        (install_dir / "requirements.txt").write_text("PySide6-Essentials\n")

        self.make_command(fake_bin, "uname", "printf 'Darwin\\n'")
        self.make_command(
            fake_bin,
            "git",
            """
printf '%s\n' "$*" >> "${GIT_TEST_LOG}"
case "$*" in
  *"status --porcelain"*)
    if [ "${GIT_TEST_DIRTY:-no}" = "yes" ]; then
      printf ' M main.py\n'
    fi
    ;;
  *"rev-parse --short HEAD"*) printf 'abc123\n' ;;
esac
exit 0
""".strip(),
        )
        python = self.make_command(
            install_dir / ".venv" / "bin",
            "python",
            'printf \'%s\\n\' "$*" >> "${PYTHON_TEST_LOG}"',
        )
        self.assertTrue(os.access(python, os.X_OK))
        creator = install_dir / "scripts" / "create-mac-app.sh"
        creator.write_text(
            "#!/bin/bash\nprintf '%s\\n' \"$*\" > \"${APP_TEST_LOG}\"\n",
            encoding="utf-8",
        )
        creator.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(fake_home),
                "PATH": f"{fake_bin}:/usr/bin:/bin",
                "ATOZ_INSTALL_DIR": str(install_dir),
                "ATOZ_MAC_APP_PATH": str(app_path),
                "GIT_TEST_LOG": str(git_log),
                "PYTHON_TEST_LOG": str(python_log),
                "APP_TEST_LOG": str(app_log),
            }
        )
        return install_dir, app_path, environment, git_log, python_log, app_log

    def test_update_pulls_main_refreshes_dependencies_and_rebuilds_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir, app_path, environment, git_log, python_log, app_log = (
                self.make_update_install(temp_dir)
            )

            result = subprocess.run(
                ["/bin/bash", str(UPDATE_SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )

            git_commands = git_log.read_text(encoding="utf-8")
            python_commands = python_log.read_text(encoding="utf-8")
            app_command = app_log.read_text(encoding="utf-8")
            self.assertIn("pull --ff-only origin main", git_commands)
            self.assertIn("remote set-url origin", git_commands)
            self.assertIn(f"-m pip install -r {install_dir}/requirements.txt", python_commands)
            self.assertIn("-m pip check", python_commands)
            self.assertIn(f"--project-dir {install_dir}", app_command)
            self.assertIn(f"--app-path {app_path}", app_command)
            self.assertIn("Update complete at revision abc123", result.stdout)

    def test_update_refuses_to_overwrite_tracked_local_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, _, environment, git_log, _, _ = self.make_update_install(temp_dir)
            environment["GIT_TEST_DIRTY"] = "yes"

            result = subprocess.run(
                ["/bin/bash", str(UPDATE_SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("pull --ff-only", git_log.read_text(encoding="utf-8"))
            self.assertIn("tracked project files have local changes", result.stderr)

    def test_scripts_have_valid_shell_syntax(self):
        subprocess.run(["bash", "-n", str(CREATE_APP_SCRIPT)], check=True)
        subprocess.run(["bash", "-n", str(BOOTSTRAP_APP_SCRIPT)], check=True)
        subprocess.run(["bash", "-n", str(PACKAGE_APP_SCRIPT)], check=True)
        subprocess.run(["bash", "-n", str(UPDATE_SCRIPT)], check=True)


if __name__ == "__main__":
    unittest.main()
