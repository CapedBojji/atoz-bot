#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
BOT_LOG_PATH = PROJECT_ROOT / "app.log"
DEFAULT_MAC_APP_PATH = Path.home() / "Applications" / "AtoZ Bot.app"
MANUAL_LOGIN_PROMPTS = (
    "press enter here to continue",
    "login cookies were not detected yet",
)
BOT_RUNNING_EVENT = "ATOZ_EVENT:BOT_RUNNING"


def bot_arguments(project_root: Path = PROJECT_ROOT) -> list[str]:
    return [
        str(project_root / "main.py"),
        "--manual_login",
        "--config_dir",
        str(project_root / "config"),
        "--log_file",
        str(project_root / "app.log"),
    ]


def update_arguments(project_root: Path = PROJECT_ROOT) -> list[str]:
    return [str(project_root / "scripts" / "update-mac.sh")]


def contains_manual_login_prompt(output: str) -> bool:
    lowered = output.lower()
    return any(prompt in lowered for prompt in MANUAL_LOGIN_PROMPTS)


def process_environment() -> QProcessEnvironment:
    environment = QProcessEnvironment.systemEnvironment()
    path_parts = ["/opt/homebrew/bin", "/usr/local/bin"]
    current_path = environment.value("PATH")
    if current_path:
        path_parts.append(current_path)
    environment.insert("PATH", ":".join(path_parts))

    for geckodriver in (
        Path("/opt/homebrew/bin/geckodriver"),
        Path("/usr/local/bin/geckodriver"),
    ):
        if geckodriver.is_file():
            environment.insert("GECKODRIVER_PATH", str(geckodriver))
            break

    firefox = Path("/Applications/Firefox.app/Contents/MacOS/firefox")
    if firefox.is_file():
        environment.insert("FIREFOX_BIN", str(firefox))
    return environment


def process_running(process: QProcess) -> bool:
    return process.state() != QProcess.ProcessState.NotRunning


def stop_process(process: QProcess, timeout_ms: int = 8000) -> None:
    if not process_running(process):
        return
    process.closeWriteChannel()
    process.terminate()
    if not process.waitForFinished(timeout_ms):
        process.kill()
        process.waitForFinished(2000)


class AtoZMacApp(QMainWindow):
    def __init__(
        self,
        project_root: Path = PROJECT_ROOT,
        mac_app_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.project_root = project_root.resolve()
        self.config_dir = self.project_root / "config"
        self.mac_app_path = (
            mac_app_path
            or Path(os.getenv("ATOZ_MAC_APP_PATH", str(DEFAULT_MAC_APP_PATH)))
        ).expanduser()
        self._closing = False
        self._bot_prompt_buffer = ""

        self.bot_process = self._new_process()
        self.update_process = self._new_process()
        self.config_process = self._new_process()

        self._build_window()
        self._connect_processes()
        self.refresh_controls()

        if not self.config_files():
            self.status_label.setText(
                "First run: create a config, then start manual login."
            )
            QTimer.singleShot(500, self.open_config_builder)

    def _new_process(self) -> QProcess:
        process = QProcess(self)
        process.setWorkingDirectory(str(self.project_root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.setProcessEnvironment(process_environment())
        return process

    def _build_window(self) -> None:
        self.setWindowTitle("AtoZ Bot")
        self.setMinimumSize(760, 650)
        self.resize(820, 700)

        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(16)

        title = QLabel("AtoZ Bot")
        title.setObjectName("title")
        subtitle = QLabel(
            "Configure shifts, update safely, and control manual login from one place."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QVBoxLayout(status_frame)
        status_heading = QLabel("Status")
        status_heading.setObjectName("sectionTitle")
        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.config_label = QLabel()
        self.config_label.setObjectName("detail")
        self.config_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.config_label.setWordWrap(True)
        status_layout.addWidget(status_heading)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.config_label)
        layout.addWidget(status_frame)

        primary_buttons = QHBoxLayout()
        self.start_button = QPushButton("Start App · Manual Login")
        self.start_button.setObjectName("primaryButton")
        self.continue_button = QPushButton("Continue After Login")
        self.continue_button.setObjectName("continueButton")
        primary_buttons.addWidget(self.start_button)
        primary_buttons.addWidget(self.continue_button)
        layout.addLayout(primary_buttons)

        utility_buttons = QHBoxLayout()
        self.config_button = QPushButton("Configure")
        self.update_button = QPushButton("Update from GitHub")
        self.close_button = QPushButton("Close App")
        self.close_button.setObjectName("closeButton")
        utility_buttons.addWidget(self.config_button)
        utility_buttons.addWidget(self.update_button)
        utility_buttons.addWidget(self.close_button)
        layout.addLayout(utility_buttons)

        output_heading = QLabel("Activity")
        output_heading.setObjectName("sectionTitle")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(1500)
        self.output.setPlaceholderText(
            "Setup, update, login, and bot messages appear here."
        )
        layout.addWidget(output_heading)
        layout.addWidget(self.output, stretch=1)

        self.setCentralWidget(page)
        self.setStyleSheet(
            """
            QWidget#page { background: #f4f6f8; color: #172033; }
            QLabel#title { font-size: 30px; font-weight: 750; }
            QLabel#subtitle { color: #526176; font-size: 14px; }
            QLabel#sectionTitle { font-size: 14px; font-weight: 700; }
            QLabel#status { color: #173f79; font-size: 15px; font-weight: 650; }
            QLabel#detail { color: #526176; font-size: 12px; }
            QFrame#statusFrame {
                background: white;
                border: 1px solid #d2d9e3;
                border-radius: 10px;
            }
            QPlainTextEdit {
                background: #111827;
                color: #d7e0ec;
                border: 1px solid #253247;
                border-radius: 9px;
                padding: 9px;
                font-family: Menlo, Monaco, monospace;
                font-size: 12px;
            }
            QPushButton {
                min-height: 40px;
                border: 1px solid #bcc7d6;
                border-radius: 8px;
                background: white;
                padding: 4px 14px;
                font-size: 14px;
                font-weight: 650;
            }
            QPushButton:hover { background: #eaf0f8; }
            QPushButton:disabled { color: #99a4b3; background: #e9edf2; }
            QPushButton#primaryButton {
                background: #2463d4;
                color: white;
                border: none;
            }
            QPushButton#primaryButton:hover { background: #174ea6; }
            QPushButton#continueButton {
                background: #16845b;
                color: white;
                border: none;
            }
            QPushButton#continueButton:hover { background: #0f6746; }
            QPushButton#continueButton:disabled {
                color: #99a4b3;
                background: #e9edf2;
            }
            QPushButton#closeButton { color: #9f2d2d; }
            """
        )

        self.start_button.clicked.connect(self.start_bot)
        self.continue_button.clicked.connect(self.continue_login)
        self.config_button.clicked.connect(self.open_config_builder)
        self.update_button.clicked.connect(self.update_app)
        self.close_button.clicked.connect(self.close)

    def _connect_processes(self) -> None:
        self.bot_process.readyReadStandardOutput.connect(self.read_bot_output)
        self.bot_process.started.connect(self.bot_started)
        self.bot_process.finished.connect(self.bot_finished)
        self.bot_process.errorOccurred.connect(self.bot_error)

        self.update_process.readyReadStandardOutput.connect(
            lambda: self.read_process_output(self.update_process, "Update")
        )
        self.update_process.started.connect(self.update_started)
        self.update_process.finished.connect(self.update_finished)
        self.update_process.errorOccurred.connect(
            lambda error: self.child_process_error("Update", self.update_process, error)
        )

        self.config_process.readyReadStandardOutput.connect(
            lambda: self.read_process_output(self.config_process, "Config")
        )
        self.config_process.finished.connect(self.config_finished)
        self.config_process.errorOccurred.connect(
            lambda error: self.child_process_error("Config", self.config_process, error)
        )

    def config_files(self) -> list[Path]:
        return sorted(self.config_dir.glob("*.toml")) if self.config_dir.is_dir() else []

    def append_output(self, label: str, text: str) -> None:
        text = text.rstrip()
        if text:
            self.output.appendPlainText(f"[{label}] {text}")

    def read_process_output(self, process: QProcess, label: str) -> str:
        text = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.append_output(label, text)
        return text

    def refresh_controls(self) -> None:
        bot_running = process_running(self.bot_process)
        update_running = process_running(self.update_process)
        config_running = process_running(self.config_process)
        configs = self.config_files()

        self.start_button.setEnabled(
            bool(configs) and not bot_running and not update_running and not config_running
        )
        self.continue_button.setEnabled(False)
        self.config_button.setEnabled(
            not bot_running and not update_running and not config_running
        )
        self.update_button.setEnabled(
            not bot_running and not update_running and not config_running
        )
        self.config_label.setText(
            f"Configs: {len(configs)} · {self.config_dir}\n"
            f"Install: {self.project_root}"
        )

    def start_bot(self) -> None:
        if process_running(self.bot_process):
            return
        if not self.config_files():
            QMessageBox.warning(
                self,
                "Config required",
                "Create at least one config before starting the bot.",
            )
            self.open_config_builder()
            return

        self.append_output("App", "Starting bot in manual-login mode.")
        self._bot_prompt_buffer = ""
        self.status_label.setText("Starting manual login…")
        self.start_button.setEnabled(False)
        self.config_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.bot_process.setProgram(str(self.project_root / ".venv" / "bin" / "python"))
        self.bot_process.setArguments(bot_arguments(self.project_root))
        self.bot_process.start()

    def bot_started(self) -> None:
        self.status_label.setText(
            "Firefox is opening. Finish login there, then return here."
        )

    def read_bot_output(self) -> None:
        text = self.read_process_output(self.bot_process, "Bot")
        self._bot_prompt_buffer = (self._bot_prompt_buffer + text)[-1000:]
        if contains_manual_login_prompt(self._bot_prompt_buffer):
            self._bot_prompt_buffer = ""
            self.status_label.setText(
                "Login waiting: finish in Firefox, then click Continue After Login."
            )
            self.continue_button.setEnabled(True)
        if BOT_RUNNING_EVENT in text:
            self.status_label.setText("Bot is running and watching for matching shifts.")
            self.continue_button.setEnabled(False)

    def continue_login(self) -> None:
        if not process_running(self.bot_process):
            self.continue_button.setEnabled(False)
            return
        if self.bot_process.write(b"\n") < 0:
            self.status_label.setText("Could not send Continue to the bot.")
            return
        self.bot_process.waitForBytesWritten(1000)
        self.continue_button.setEnabled(False)
        self.status_label.setText("Checking login and starting bot…")
        self.append_output("App", "Continue sent after manual login.")

    def bot_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self._closing:
            return
        if self.bot_process.bytesAvailable():
            self.read_bot_output()
        self.append_output("App", f"Bot stopped with exit code {exit_code}.")
        self.status_label.setText(
            "Bot stopped." if exit_code == 0 else f"Bot stopped with error {exit_code}."
        )
        self.refresh_controls()

    def bot_error(self, error: QProcess.ProcessError) -> None:
        if self._closing:
            return
        self.status_label.setText(f"Could not run bot: {error.name}")
        self.append_output("App", self.bot_process.errorString())
        self.refresh_controls()

    def open_config_builder(self) -> None:
        if process_running(self.config_process) or process_running(self.bot_process):
            return
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status_label.setText("Config builder open.")
        self.append_output("App", f"Opening config builder for {self.config_dir}")
        self.config_process.setProgram(
            str(self.project_root / ".venv" / "bin" / "python")
        )
        self.config_process.setArguments(
            [
                str(self.project_root / "scripts" / "config-builder.py"),
                "--config-dir",
                str(self.config_dir),
            ]
        )
        self.config_process.start()
        self.refresh_controls()

    def config_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self._closing:
            return
        if self.config_process.bytesAvailable():
            self.read_process_output(self.config_process, "Config")
        configs = self.config_files()
        if configs:
            self.status_label.setText(
                f"Config ready: {configs[-1].name}. You can start manual login."
            )
        elif exit_code != 0:
            self.status_label.setText("Config builder closed without a config.")
        self.refresh_controls()

    def update_app(self) -> None:
        if process_running(self.update_process) or process_running(self.bot_process):
            return
        answer = QMessageBox.question(
            self,
            "Update AtoZ Bot?",
            "Pull the latest code from GitHub and refresh app dependencies?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.update_process.setProgram("/bin/bash")
        self.update_process.setArguments(update_arguments(self.project_root))
        self.update_process.start()
        self.refresh_controls()

    def update_started(self) -> None:
        self.status_label.setText("Updating from GitHub…")
        self.append_output("App", "Update started.")

    def update_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self._closing:
            return
        if self.update_process.bytesAvailable():
            self.read_process_output(self.update_process, "Update")
        if exit_code == 0:
            self.status_label.setText(
                "Update installed. Close and reopen AtoZ Bot to use the new version."
            )
            self.append_output("App", "Update completed successfully.")
        else:
            self.status_label.setText(
                f"Update failed with exit code {exit_code}. See Activity."
            )
        self.refresh_controls()

    def child_process_error(
        self,
        label: str,
        process: QProcess,
        error: QProcess.ProcessError,
    ) -> None:
        if self._closing:
            return
        self.status_label.setText(f"{label} could not run: {error.name}")
        self.append_output(label, process.errorString())
        self.refresh_controls()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self.status_label.setText("Closing bot and browser…")
        QApplication.processEvents()
        stop_process(self.config_process, timeout_ms=3000)
        stop_process(self.update_process, timeout_ms=3000)
        stop_process(self.bot_process, timeout_ms=8000)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AtoZ Bot")
    app.setOrganizationName("AtoZ Bot")
    window = AtoZMacApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
