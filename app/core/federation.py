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
