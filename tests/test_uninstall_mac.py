import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNINSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "uninstall-mac.sh"


class MacUninstallTests(unittest.TestCase):
    def make_command(self, bin_dir: Path, name: str, body: str) -> Path:
        command = bin_dir / name
        command.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        command.chmod(0o755)
        return command

    def make_environment(self, temp_dir: str) -> tuple[Path, dict[str, str]]:
        fake_home = Path(temp_dir) / "home"
        fake_bin = Path(temp_dir) / "bin"
        fake_home.mkdir()
        fake_bin.mkdir()
        self.make_command(fake_bin, "uname", "printf 'Darwin\\n'")
        self.make_command(
            fake_bin,
            "brew",
            'if [ "$1" = "list" ]; then exit 1; fi\nexit 0',
        )
        environment = os.environ.copy()
        environment["HOME"] = str(fake_home)
        environment["PATH"] = f"{fake_bin}:/usr/bin:/bin"
        return fake_home, environment

    def run_uninstaller(
        self,
        environment: dict[str, str],
        answers: str = "",
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(UNINSTALL_SCRIPT), *arguments],
            input=answers,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )

    def create_app_install(self, fake_home: Path) -> tuple[Path, Path, Path, Path]:
        install_dir = fake_home / "atoz-bot"
        launcher_path = fake_home / "Desktop" / "Run AtoZ Bot.command"
        mac_app_path = fake_home / "Applications" / "AtoZ Bot.app"
        manifest_path = fake_home / ".atozbot-install-manifest"

        (install_dir / "config").mkdir(parents=True)
        (install_dir / ".venv" / "lib" / "PySide6").mkdir(parents=True)
        (install_dir / "O365_tokens").mkdir()
        (install_dir / "config" / "worker.toml").write_text("config")
        (install_dir / "app.log").write_text("log")
        launcher_path.parent.mkdir()
        launcher_path.write_text("launcher")
        (mac_app_path / "Contents" / "MacOS").mkdir(parents=True)
        (mac_app_path / "Contents" / "MacOS" / "AtoZ Bot").write_text("app")
        manifest_path.write_text(
            f"project:{install_dir}\n"
            f"launcher:{launcher_path}\n"
            f"mac-app:{mac_app_path}\n",
            encoding="utf-8",
        )
        return install_dir, launcher_path, mac_app_path, manifest_path

    def test_removes_app_private_data_launcher_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            install_dir, launcher_path, mac_app_path, manifest_path = (
                self.create_app_install(fake_home)
            )

            result = self.run_uninstaller(environment, "\n")

            self.assertFalse(install_dir.exists())
            self.assertFalse(launcher_path.exists())
            self.assertFalse(mac_app_path.exists())
            self.assertFalse(manifest_path.exists())
            self.assertIn("No setup-owned items remain tracked", result.stdout)

    def test_kept_project_stays_tracked_for_future_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            install_dir, launcher_path, mac_app_path, manifest_path = (
                self.create_app_install(fake_home)
            )

            result = self.run_uninstaller(environment, "no\n")

            self.assertTrue(install_dir.exists())
            self.assertFalse(launcher_path.exists())
            self.assertFalse(mac_app_path.exists())
            self.assertEqual(
                manifest_path.read_text(encoding="utf-8"),
                f"project:{install_dir}\n",
            )
            self.assertIn("items kept or not removed", result.stderr)

    def test_dry_run_removes_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            install_dir, launcher_path, mac_app_path, manifest_path = (
                self.create_app_install(fake_home)
            )

            result = self.run_uninstaller(environment, "\n", "--dry-run")

            self.assertTrue(install_dir.exists())
            self.assertTrue(launcher_path.exists())
            self.assertTrue(mac_app_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertIn("Dry run complete. Nothing was removed", result.stdout)

    def test_removes_setup_owned_mise_python_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            fake_bin = Path(temp_dir) / "bin"
            manifest_path = fake_home / ".atozbot-install-manifest"
            mise_log = Path(temp_dir) / "mise.log"
            manifest_path.write_text("mise-tool:python@3.12\n", encoding="utf-8")
            environment["MISE_TEST_LOG"] = str(mise_log)
            self.make_command(
                fake_bin,
                "mise",
                """
if [ "$1" = "where" ]; then
  exit 0
fi
if [ "$1" = "uninstall" ]; then
  printf '%s\\n' "$*" > "${MISE_TEST_LOG}"
  exit 0
fi
exit 1
""".strip(),
            )

            self.run_uninstaller(environment, "\n")

            self.assertEqual(
                mise_log.read_text(encoding="utf-8").strip(),
                "uninstall -y python@3.12",
            )
            self.assertFalse(manifest_path.exists())

    def test_removes_only_manifest_tracked_homebrew_dependencies_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            fake_bin = Path(temp_dir) / "bin"
            manifest_path = fake_home / ".atozbot-install-manifest"
            brew_log = Path(temp_dir) / "brew.log"
            manifest_path.write_text(
                "brew:geckodriver\n"
                "brew:mise\n"
                "brew:git\n"
                "brew-cask:firefox\n",
                encoding="utf-8",
            )
            environment["BREW_TEST_LOG"] = str(brew_log)
            self.make_command(
                fake_bin,
                "brew",
                """
if [ "$1" = "list" ]; then
  exit 0
fi
if [ "$1" = "uninstall" ]; then
  printf '%s\\n' "$*" >> "${BREW_TEST_LOG}"
  exit 0
fi
exit 1
""".strip(),
            )

            self.run_uninstaller(environment, "\n\n\n\n")

            self.assertEqual(
                brew_log.read_text(encoding="utf-8").splitlines(),
                [
                    "uninstall geckodriver",
                    "uninstall mise",
                    "uninstall git",
                    "uninstall --cask firefox",
                ],
            )
            self.assertFalse(manifest_path.exists())

    def test_refuses_broad_install_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home, environment = self.make_environment(temp_dir)
            marker = fake_home / "must-stay.txt"
            marker.write_text("safe", encoding="utf-8")
            environment["ATOZ_INSTALL_DIR"] = str(fake_home)

            result = subprocess.run(
                ["/bin/bash", str(UNINSTALL_SCRIPT)],
                text=True,
                capture_output=True,
                env=environment,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(marker.exists())
            self.assertIn("refusing unsafe install path", result.stderr)

    def test_script_has_valid_shell_syntax(self):
        subprocess.run(["bash", "-n", str(UNINSTALL_SCRIPT)], check=True)


if __name__ == "__main__":
    unittest.main()
