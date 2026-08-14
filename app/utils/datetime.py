import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))

def _fmt_dt(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(KST).isoformat()

def now():
    return datetime.datetime.now(datetime.UTC)

def get_24hours_later():
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)

