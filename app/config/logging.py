import contextlib
import datetime
import logging
import logging.handlers
import os
import time


class _MidnightRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Midnight-rotating handler that keeps one clean YYYY-MM-DD.log per day.

    TimedRotatingFileHandler reopens the same base filename after every rollover,
    so a plain subclass would keep writing the whole week into the startup day's
    file. Here we advance ``baseFilename`` to the new date on each rollover and
    prune archives older than ``backupCount`` days.
    """

    def __init__(self, log_dir: str):
        self._log_dir = log_dir
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join(log_dir, f"{today}.log")
        super().__init__(filepath, when="midnight", interval=1, backupCount=30, encoding="utf-8")

    def _daily_path(self, date: datetime.date) -> str:
        return os.path.join(self._log_dir, f"{date:%Y-%m-%d}.log")

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None

        now = datetime.datetime.now()
        # baseFilename은 방금까지 '어제' 이름이었으므로 그대로 두면 과거 로그로 남는다.
        # 새 날짜 이름으로 옮겨 자정 이후의 로그가 오늘 파일에 쌓이게 한다.
        self.baseFilename = self._daily_path(now)
        if not self.delay:
            self.stream = self._open()

        # 다음 자정 시각 재계산 (DST 경계도 안전하게 기본 doRollover와 동일하게)
        t = int(time.time())
        new_rollover_at = self.computeRollover(t)
        while new_rollover_at <= t:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at

    def getFilesToDelete(self):
        """backupCount일보다 오래된 YYYY-MM-DD.log 아카이브만 남긴다."""
        if self.backupCount <= 0:
            return []
        cutoff = datetime.datetime.now() - datetime.timedelta(days=self.backupCount)
        result = []
        try:
            for name in os.listdir(self._log_dir):
                if not (len(name) == 14 and name.endswith(".log")):
                    continue
                try:
                    day = datetime.datetime.strptime(name[:-4], "%Y-%m-%d")
                except ValueError:
                    continue
                if day < cutoff:
                    result.append(os.path.join(self._log_dir, name))
        except OSError:
            return []
        return result


# ── logging configuration ──
_log_handlers: list[logging.Handler] = [logging.StreamHandler()]
_log_file_dir = "logs"
if _log_file_dir:
    os.makedirs(_log_file_dir, exist_ok=True)
    with contextlib.suppress(PermissionError):
        _log_handlers.append(_MidnightRotatingFileHandler(_log_file_dir))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_log_handlers,
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.ERROR)
logging.getLogger("python_multipart.multipart").setLevel(logging.ERROR)

_request_logger = logging.getLogger("writ.request")
