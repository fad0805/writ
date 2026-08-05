from urllib.parse import urlparse

from app.config.settings import DOMAIN
from app.db.database import get_session
from app.models import ServerSetting, FederationBlock, AllowedServer


def federation_allowed(domain: str) -> bool:
    if not domain:
        return False
    if domain.lower().strip() == DOMAIN.lower().strip():
        return True
    with get_session() as s:
        try:
            settings = s.query(ServerSetting).first()
            if not settings:
                return True
            mode = settings.federation_mode or "blacklist"
            domain = domain.lower().strip()
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                return allowed is not None
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                return blocked is None
        except Exception:
            return False


def _check_fetch_domain_allowed(url: str) -> str | None:
    """Return an error message if the URL's domain is federated-blocked, else None."""
    domain = urlparse(url).hostname or ""
    if domain:
        with get_session() as s:
            mode = ServerSetting.get(s).federation_mode or "blacklist"
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                if not allowed:
                    return f"허용되지 않은 서버입니다: {domain}"
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                if blocked:
                    reason = f" ({blocked.reason})" if blocked.reason else ""
                    return f"차단된 서버입니다{reason}: {domain}"
    return None
