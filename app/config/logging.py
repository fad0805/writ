import os
import datetime
import logging
import logging.handlers
import sys


class _MidnightRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """FileHandler that rotates at midnight, creating YYYY-MM-DD.log files."""

    def __init__(self, log_dir: str):
        self._log_dir = log_dir
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join(log_dir, f"{today}.log")
        super().__init__(filepath, when="midnight", interval=1, backupCount=30, encoding="utf-8")
        self.suffix = "%Y-%m-%d"

    def rotation_filename(self, default_name: str) -> str:
        base, ext = os.path.splitext(default_name)
        now = datetime.datetime.now()
        return os.path.join(self._log_dir, f"{now.strftime(self.suffix)}{ext}")


# ── logging configuration ──
_log_handlers = [logging.StreamHandler()]
_log_file_dir = "logs"
if _log_file_dir:
    os.makedirs(_log_file_dir, exist_ok=True)
    try:
        _log_handlers.append(_MidnightRotatingFileHandler(_log_file_dir))
    except PermissionError:
        print(f"[WARN] Cannot write to log file logs/ - check permissions", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_log_handlers,
)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.ERROR)
logging.getLogger("python_multipart.multipart").setLevel(logging.ERROR)

_request_logger = logging.getLogger("writ.request")
