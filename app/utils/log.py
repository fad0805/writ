import logging
from app.models import AdminLog, get_session

logger = logging.getLogger("writ.audit")


def log_admin_action(
    user_id: int | None,
    username: str,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    target_username: str = "",
    details: str = "",
    ip_address: str = "",
):
    """Persist an admin-relevant action to the DB and write to the audit log."""
    try:
        with get_session() as s:
            s.add(AdminLog(
                user_id=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=target_id,
                target_username=target_username,
                details=details,
                ip_address=ip_address,
            ))
            s.commit()
    except Exception as exc:
        logger.error("Failed to persist admin log: %s", exc)

    logger.info(
        "[%s] %s | target=%s(%s) | ip=%s | %s",
        action, username, target_type or "-", target_username or str(target_id or "-"), ip_address, details,
    )
