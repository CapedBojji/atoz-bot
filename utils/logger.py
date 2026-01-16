import logging
import sys
from datetime import datetime
from pathlib import Path

class IntelliJFormatter(logging.Formatter):
    converter = datetime.fromtimestamp

    def formatTime(self, record, _datefmt=None):
        ct = self.converter(record.created)
        t = ct.strftime("%Y-%m-%d %H:%M:%S")
        return f"{t},{int(record.msecs):03d}"

def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    """
    Configure root logger to write to `log_file` if given,
    otherwise to stdout.
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    fmt = IntelliJFormatter(
        fmt='%(asctime)s [%(process)d] %(levelname)s - %(name)s - %(message)s'
    )
    # Choose handler: FileHandler if path given, else StreamHandler(sys.stdout)
    if log_file:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    logger.addHandler(handler)


