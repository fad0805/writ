import os
import datetime
import logging

# ── logging configuration ──
_log_handlers = [logging.StreamHandler()]
_log_file_dir = "logs"
if _log_file_dir:
    os.makedirs(_log_file_dir, exist_ok=True)
    _log_date = datetime.datetime.now().strftime("%Y-%m-%d")
    _log_handlers.append(logging.FileHandler(os.path.join(_log_file_dir, f"{_log_date}.log")))
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_log_handlers,
)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("python_multipart.multipart").setLevel(logging.ERROR)

_request_logger = logging.getLogger("writ.request")
logger = logging.getLogger("writ.api")
