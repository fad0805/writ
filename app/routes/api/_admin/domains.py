"""Domain-level federation admin endpoints (blocked domains, federation blocks, allowed servers, mode)."""

from fastapi import APIRouter, Form, HTTPException, Request

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import (
    AllowedServer,
    BlockedDomain,
    FederationBlock,
    ServerSetting,
)
from app.utils.log import log_admin_action

router = APIRouter()


@router.get("/admin/blocked-domains")
def api_admin_list_blocked_domains(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        domains = s.query(BlockedDomain).order_by(BlockedDomain.created_at.desc()).all()
        return {"domains": [{
            "id": d.id,
            "domain": d.domain,
            "created_by": d.created_by.username if d.created_by else "",
            "created_at": str(d.created_at) if d.created_at else "",
        } for d in domains]}


@router.post("/admin/block-domain")
def api_admin_block_domain(request: Request, domain: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(BlockedDomain).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already blocked")
        s.add(BlockedDomain(domain=domain, created_by_id=user.id))
        s.commit()
    log_admin_action(user.id, user.username, "block_domain", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@router.delete("/admin/block-domain/{domain}")
def api_admin_unblock_domain(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        bd = s.query(BlockedDomain).filter_by(domain=domain).first()
        if not bd:
            raise HTTPException(status_code=404, detail="Domain not blocked")
        s.delete(bd)
        s.commit()
    log_admin_action(user.id, user.username, "unblock_domain", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.get("/admin/federation-blocks")
def api_admin_list_federation_blocks(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        blocks = s.query(FederationBlock).order_by(FederationBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "domain": b.domain, "reason": b.reason or "", "created_by": b.created_by.username if b.created_by else "", "created_at": str(b.created_at) if b.created_at else ""} for b in blocks]}


@router.post("/admin/federation-block")
def api_admin_add_federation_block(request: Request, domain: str = Form(...), reason: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(FederationBlock).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already blocked")
        s.add(FederationBlock(domain=domain, reason=reason, created_by_id=user.id))
        # Also remove from allowed list if present
        s.query(AllowedServer).filter_by(domain=domain).delete()
        s.commit()
    log_admin_action(user.id, user.username, "federation_block", target_type="domain", target_username=domain, details=reason, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@router.delete("/admin/federation-block/{domain}")
def api_admin_remove_federation_block(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        b = s.query(FederationBlock).filter_by(domain=domain).first()
        if not b:
            raise HTTPException(status_code=404, detail="Domain not blocked")
        s.delete(b)
        s.commit()
    log_admin_action(user.id, user.username, "federation_unblock", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.get("/admin/allowed-servers")
def api_admin_list_allowed_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        servers = s.query(AllowedServer).order_by(AllowedServer.created_at.desc()).all()
        return {"servers": [{"id": sv.id, "domain": sv.domain, "created_by": sv.created_by.username if sv.created_by else "", "created_at": str(sv.created_at) if sv.created_at else ""} for sv in servers]}


@router.post("/admin/allowed-server")
def api_admin_add_allowed_server(request: Request, domain: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    with get_session() as s:
        existing = s.query(AllowedServer).filter_by(domain=domain).first()
        if existing:
            raise HTTPException(status_code=400, detail="Already allowed")
        # Also remove from block list if present
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.add(AllowedServer(domain=domain, created_by_id=user.id))
        s.commit()
    log_admin_action(user.id, user.username, "federation_allow", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True, "domain": domain}


@router.delete("/admin/allowed-server/{domain}")
def api_admin_remove_allowed_server(request: Request, domain: str):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    domain = domain.strip().lower()
    with get_session() as s:
        sv = s.query(AllowedServer).filter_by(domain=domain).first()
        if not sv:
            raise HTTPException(status_code=404, detail="Domain not allowed")
        s.delete(sv)
        s.commit()
    log_admin_action(user.id, user.username, "federation_disallow", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/federation-mode")
def api_admin_set_federation_mode(request: Request, mode: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if mode not in ("whitelist", "blacklist"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    with get_session() as s:
        settings = ServerSetting.get(s)
        old_mode = settings.federation_mode
        settings.federation_mode = mode
        s.commit()
    log_admin_action(user.id, user.username, "federation_mode", details=f"{old_mode} -> {mode}", ip_address=request.client.host if request.client else "")
    return {"ok": True, "mode": mode}


@router.get("/admin/federation-mode")
def api_admin_get_federation_mode(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        settings = ServerSetting.get(s)
        return {"mode": settings.federation_mode or "blacklist"}
