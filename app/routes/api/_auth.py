"""Auth endpoints — login, register, password reset, email verification extracted from _core.py."""
import contextlib
import ipaddress
import json
import logging
import re
import secrets
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.settings import (
    APP_ENV,
    BASE_URL,
    INITIAL_OWNER_PASSWORD,
    SECRET_KEY,
    SMTP_FROM,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USER,
)
from app.core.auth import (
    create_session,
    delete_session_by_key,
    get_current_user,
    get_session_key_from_cookie,
    hash_password,
    session_key_from_token,
    verify_password,
)
from app.core.permissions import get_user_permissions
from app.db.database import get_db, get_session
from app.models import BlockedDomain, LoginSession, Notification, ServerSetting, User
from app.serializers import _user_json
from app.utils.crypto import encrypt_key, generate_csrf_token, generate_keypair, validate_csrf_token
from app.utils.log import log_admin_action

logger = logging.getLogger("writ.api.auth")

auth_router = APIRouter()

# Auth rate limiting (IP-based, in-memory)
_auth_failures: dict[str, list[float]] = {}
_auth_lock = threading.Lock()
_AUTH_FAIL_WINDOW = 900  # 15 min
_AUTH_FAIL_MAX = 5
_AUTH_FAIL_BACKOFF_BASE = 60  # 1 min base

def _check_auth_rate_limit(ip: str) -> bool:
    now = time.time()
    with _auth_lock:
        timestamps = [t for t in _auth_failures.get(ip, []) if t > now - _AUTH_FAIL_WINDOW]
        _auth_failures[ip] = timestamps
        if len(timestamps) >= _AUTH_FAIL_MAX:
            return False
        timestamps.append(now)
        return True

def _record_auth_failure(ip: str):
    now = time.time()
    with _auth_lock:
        _auth_failures.setdefault(ip, []).append(now)

def _get_auth_backoff_seconds(ip: str) -> int:
    with _auth_lock:
        count = len([t for t in _auth_failures.get(ip, []) if t > time.time() - _AUTH_FAIL_WINDOW])
        if len(_auth_failures) > 5000:
            _auth_failures.clear()
    if count < _AUTH_FAIL_MAX:
        return 0
    return _AUTH_FAIL_BACKOFF_BASE * (2 ** min(count - _AUTH_FAIL_MAX, 6))


_PRIVATE_PEER_SUBNETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

def _get_client_ip(request) -> str:
    """Rate-limit key for the client.

    XFF는 직접 연결 피어가 사설/루프백 주소(즉 로컬 리버스 프록시)일 때만 신뢰한다.
    이렇게 하면 앱에 직접 붙은 공격자가 XFF 헤더를 조작해 IP를 계속 바꾸며
    레이트리밋을 우회할 수 없다.
    """
    peer = request.client.host if request.client else ""
    peer_bare = peer.split("%")[0]
    try:
        peer_ip = ipaddress.ip_address(peer_bare)
    except ValueError:
        peer_ip = None
    is_private_peer = bool(peer_ip and any(peer_ip in net for net in _PRIVATE_PEER_SUBNETS))
    if is_private_peer:
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if xff:
            try:
                ipaddress.ip_address(xff.split("%")[0])
                return xff
            except ValueError:
                pass
    return peer


RESERVED_HANDLES = frozenset({
    "admin", "administrator", "root", "system", "moderator", "support",
    "nodeinfo", "well-known", "api", "auth", "oauth", "inbox", "outbox",
    "actor", "users", "accounts", "instance_actor", "login", "register", "writ",
})


def _send_verification_email(u: User):
    if not SMTP_SERVER:
        if APP_ENV == "development":
            u.email_verified = True  # type: ignore[assignment]
            return
        logger.warning("SMTP not configured — email %s left unverified", u.email)
        return
    token = secrets.token_urlsafe(32)
    u.verification_token = token  # type: ignore[assignment]
    verify_url = f"{BASE_URL}/verify-email?token={token}"
    try:
        msg = MIMEText(
            f"안녕하세요, {u.display_name}님.\n\n"
            f"WRIT 계정 생성을 환영합니다. 아래 링크를 클릭하여 이메일 인증을 완료해 주세요.\n\n"
            f"{verify_url}\n\n"
            f"이 링크는 24시간 동안 유효합니다.\n감사합니다.\nWRIT 팀"
        )
        msg["Subject"] = "[WRIT] 이메일 인증을 완료해 주세요"
        msg["From"] = SMTP_FROM or "noreply@writ.local"
        msg["To"] = u.email  # type: ignore[assignment]
        port = SMTP_PORT or 587
        if port == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=10) as smtp:
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_SERVER, port, timeout=10) as smtp:
                smtp.ehlo()
                if smtp.has_extn("STARTTLS"):
                    smtp.starttls()
                    smtp.ehlo()
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                smtp.send_message(msg)
    except Exception:
        logger.exception("Failed to send verification email to %s", u.email)


@auth_router.get("/auth/me")
def api_me(request: Request, s: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    result = _user_json(user)
    result["permissions"] = get_user_permissions(user)
    _settings = ServerSetting.get(s)
    if _settings.enable_reactions is False:
        result["enable_reactions"] = False
    resp = JSONResponse(result)
    secure = APP_ENV != "development"
    resp.set_cookie(key="csrf_token", value=generate_csrf_token(user.id), max_age=30*86400, httponly=False, samesite="lax", path="/", secure=secure)
    return resp


@auth_router.post("/auth/login")
def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        client_ip = _get_client_ip(request)
        backoff = _get_auth_backoff_seconds(client_ip)
        if backoff > 0:
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
        if not _check_auth_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
        with get_session() as s:
            q = s.query(User).filter(User.is_remote == False)
            if "@" in username and "." in username:
                db_user = q.filter(User.email == username).first()
            else:
                db_user = q.filter(User.username == username).first()
            if not db_user:
                log_admin_action(None, username, "login_failed", details="user_not_found", ip_address=client_ip)
                _record_auth_failure(client_ip)
                raise HTTPException(status_code=401, detail="Invalid credentials")
            if getattr(db_user, 'is_frozen', False):
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="frozen", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="계정이 동결되었습니다.")
            if getattr(db_user, 'is_suspended', False):
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="suspended", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="계정이 정지되었습니다.")
            if getattr(db_user, 'is_deactivated', False):
                if db_user.password_hash == "deleted":
                    log_admin_action(db_user.id, db_user.username, "login_blocked", details="deleted", ip_address=client_ip)
                    raise HTTPException(status_code=403, detail="탈퇴한 계정입니다.")
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="deactivated", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
            stored = db_user.password_hash
            if ":" not in stored:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            salt, hval = stored.split(":", 1)
            if not verify_password(password, salt, hval):
                log_admin_action(db_user.id, db_user.username, "login_failed", details="wrong_password", ip_address=client_ip)
                _record_auth_failure(client_ip)
                raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
            if not db_user.email_verified:
                log_admin_action(db_user.id, db_user.username, "login_blocked", details="email_not_verified", ip_address=client_ip)
                raise HTTPException(status_code=403, detail="이메일 인증이 필요합니다. 가입 시 등록한 이메일에서 인증을 완료해 주세요.")
            user_agent = request.headers.get("user-agent", "")
            token = create_session(db_user.id, ip_address=client_ip, user_agent=user_agent)
            # 이미 유효한 세션으로 로그인하면 두 계정을 서로 연결한다.
            # 이후 전환은 클라이언트 저장 토큰 없이 linked set으로 검증한다.
            prev_key = get_session_key_from_cookie(request)
            new_key = session_key_from_token(token)
            if prev_key and new_key and prev_key != new_key:
                with get_session() as ls_s:
                    prev_ls = ls_s.query(LoginSession).filter_by(session_key=prev_key).first()
                    if prev_ls and prev_ls.user_id != db_user.id:
                        linked_prev = set(prev_ls.linked_user_ids or [])
                        linked_prev.add(db_user.id)
                        prev_ls.linked_user_ids = sorted(linked_prev)
                        new_ls = ls_s.query(LoginSession).filter_by(session_key=new_key).first()
                        if new_ls:
                            linked_new = set(new_ls.linked_user_ids or [])
                            linked_new.add(prev_ls.user_id)
                            new_ls.linked_user_ids = sorted(linked_new)
                    ls_s.commit()
            if client_ip:
                ips = db_user.recent_ips or []
                ips = [ip for ip in ips if ip != client_ip]
                ips.insert(0, client_ip)
                db_user.recent_ips = ips[:10]
                s.commit()
            log_admin_action(db_user.id, db_user.username, "login", ip_address=client_ip)
            user_json = _user_json(db_user)
            resp = JSONResponse(user_json)
            secure = APP_ENV != "development"
            resp.set_cookie(key="session", value=token, max_age=30*86400, httponly=True, samesite="lax", path="/", secure=secure)
            resp.set_cookie(key="csrf_token", value=generate_csrf_token(db_user.id), max_age=3600, httponly=False, samesite="lax", path="/", secure=secure)
            return resp
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Login error")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@auth_router.post("/auth/register")
def api_register(request: Request, username: str = Form(...), password: str = Form(...),
                 display_name: str = Form(""), email: str = Form(...)):
    client_ip = _get_client_ip(request)
    if not _check_auth_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    display_handle = username
    username = username.lower()
    if username in RESERVED_HANDLES:
        raise HTTPException(status_code=400, detail="해당 아이디로 가입할 수 없습니다.")
    if not username or not password or not email:
        raise HTTPException(status_code=400, detail="Username, password, and email required")
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Username (3+) and password (6+) required")
    if not re.match(r'^[a-z0-9][a-z0-9_]{2,19}$', username):
        raise HTTPException(status_code=400, detail="아이디는 영문 소문자, 숫자, 언더바만 사용 가능하며 3~20자입니다.")
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    with get_session() as s:
        existing = s.query(User).filter_by(username=username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        existing_email = s.query(User).filter_by(email=email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain:
            blocked = s.query(BlockedDomain).filter_by(domain=domain).first()
            if blocked:
                raise HTTPException(status_code=400, detail="해당 이메일 도메인은 가입이 차단되었습니다.")
        user_count = s.query(User).count()
        is_first = user_count == 0
        if is_first and INITIAL_OWNER_PASSWORD and password != INITIAL_OWNER_PASSWORD:
            raise HTTPException(status_code=400, detail="초기 관리자 암호가 일치하지 않습니다.")
        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()
        email_verified = APP_ENV == "development"
        user = User(
            username=username,
            display_name=display_name or display_handle,
            display_handle=display_handle,
            password_hash=salt + ":" + pwd_hash,
            private_key=encrypt_key(priv_key, SECRET_KEY), public_key=pub_key,
            is_remote=False,
            role="owner" if is_first else "user",
            is_admin=is_first,
            email=email,
            email_verified=email_verified,
        )
        s.add(user)
        # 신뢰된 클라이언트 IP 추출 사용 — H4(XFF 스푸핑)와 동일한 로직으로,
        # 원시 XFF 헤더를 그대로 recent_ips에 기록하지 않는다.
        client_ip = _get_client_ip(request)
        if client_ip:
            user.recent_ips = [client_ip]  # type: ignore[assignment]
        s.flush()
        user_id = user.id

        with contextlib.suppress(Exception):
            _send_verification_email(user)
        s.commit()

        log_admin_action(int(user_id), str(user.username), "register", ip_address=client_ip, details="first_user" if is_first else "email_required")

        return {"email_sent": True}


@auth_router.post("/auth/verify-email")
def api_verify_email(request: Request, token: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(verification_token=token).first()

        if not u:
            raise HTTPException(status_code=400, detail="유효하지 않거나 이미 만료된 인증 토큰입니다.")

        u.email_verified = True
        u.verification_token = ""

        if u.role != "owner":
            admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
            for admin in admins:
                if admin.id == u.id:
                    continue
                s.add(Notification(
                    user_id=admin.id, from_user_id=u.id,
                    notification_type="moderation",
                    metadata_json=json.dumps({"type": "new_user", "user_id": u.id, "username": u.username, "display_name": u.display_name}),
                ))

        s.commit()
        return JSONResponse({"ok": True, "email_verified": True})


@auth_router.post("/auth/resend-verification")
def api_resend_verification(request: Request, email: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(email=email, email_verified=False).first()
        if not u:
            raise HTTPException(status_code=400, detail="해당 이메일로 등록된 인증 대기 계정이 없습니다.")
        _send_verification_email(u)
        s.commit()
        return {"ok": True, "email_sent": True}


@auth_router.post("/auth/forgot-password")
def api_forgot_password(request: Request, email: str = Form(...)):
    client_ip = _get_client_ip(request)
    if not _check_auth_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    with get_session() as s:
        u = s.query(User).filter_by(email=email, is_remote=False).first()
        if not u or not SMTP_SERVER:
            return {"ok": True}
        token = secrets.token_urlsafe(32)
        u.reset_token = token
        u.reset_token_expires_at = datetime.utcnow() + timedelta(hours=1)
        s.commit()
        reset_url = f"{BASE_URL}/reset-password?token={token}"
        try:
            msg = MIMEText(
                f"안녕하세요, {u.display_name or u.username}님.\n\n"
                f"WRIT 비밀번호 재설정 요청을 받았습니다.\n"
                f"아래 링크를 클릭하여 새 비밀번호를 설정해 주세요.\n\n"
                f"{reset_url}\n\n"
                f"이 링크는 1시간 동안 유효합니다.\n"
                f"요청하지 않으셨다면 이 메일을 무시해 주세요.\n\n"
                f"감사합니다.\nWRIT 팀"
            )
            msg["Subject"] = "[WRIT] 비밀번호 재설정"
            msg["From"] = SMTP_FROM or "noreply@writ.local"
            msg["To"] = u.email
            port = SMTP_PORT or 587
            if port == 465:
                with smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=10) as smtp:
                    if SMTP_USER:
                        smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_SERVER, port, timeout=10) as smtp:
                    smtp.starttls()
                    if SMTP_USER:
                        smtp.login(SMTP_USER, SMTP_PASSWORD or "")
                    smtp.send_message(msg)
        except Exception:
            logger.exception("Failed to send password reset email to %s", u.email)
    return {"ok": True}


@auth_router.post("/auth/reset-password")
def api_reset_password(request: Request, token: str = Form(...), password: str = Form(...)):
    with get_session() as s:
        u = s.query(User).filter_by(reset_token=token, is_remote=False).first()
        if not u:
            raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")
        if u.reset_token_expires_at and datetime.utcnow() > u.reset_token_expires_at:
            u.reset_token = ""
            u.reset_token_expires_at = None
            s.commit()
            raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")
        salt, hval = hash_password(password)
        u.password_hash = f"{salt}:{hval}"
        u.reset_token = ""
        u.reset_token_expires_at = None
        s.commit()
    from app.core.auth import delete_user_sessions
    delete_user_sessions(u.id)
    return {"ok": True, "password_reset": True}


@auth_router.post("/auth/logout")
def api_logout(request: Request):
    session_key = get_session_key_from_cookie(request)
    if session_key:
        delete_session_by_key(session_key)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session")
    resp.delete_cookie("csrf_token")
    return resp


@auth_router.post("/auth/switch")
def api_switch_account(request: Request, target_user_id: int = Form(...)):
    """현재 세션에 연결된(linked) 계정으로 전환한다.

    클라이언트는 토큰을 저장하지 않고 user_id만 보낸다. 서버가 현재 세션의
    linked_user_ids로 전환 허용 여부를 판정하고 새 세션 쿠키를 발급한다.
    """
    current_user = get_current_user(request)
    if not current_user:
        raise HTTPException(status_code=401, detail="로그인 상태에서만 계정 전환이 가능합니다.")
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(csrf_token, request.cookies.get("session", "")):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    session_key = get_session_key_from_cookie(request)
    if not session_key:
        raise HTTPException(status_code=401, detail="Invalid session")
    with get_session() as s:
        ls = s.query(LoginSession).filter_by(session_key=session_key).first()
        if not ls:
            raise HTTPException(status_code=401, detail="Session not found")
        linked = set(ls.linked_user_ids or [])
        if target_user_id == current_user.id or target_user_id not in linked:
            raise HTTPException(status_code=403, detail="연결되지 않은 계정입니다. 해당 계정으로 먼저 로그인해 주세요.")
        target = s.query(User).filter_by(id=target_user_id, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=401, detail="User not found")
        if getattr(target, 'is_frozen', False):
            raise HTTPException(status_code=403, detail="계정이 동결되었습니다.")
        if getattr(target, 'is_suspended', False):
            raise HTTPException(status_code=403, detail="계정이 정지되었습니다.")
        # 전환 후에도 기존 연결을 유지한다: 연결 목록 + 직전 계정 - 대상 계정
        new_linked = sorted((linked | {current_user.id}) - {target.id})
        client_ip = _get_client_ip(request)
        new_token = create_session(
            target.id,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", ""),
            linked_user_ids=new_linked,
        )
        log_admin_action(target.id, target.username, "login", details=f"switched from {current_user.username}", ip_address=client_ip)
    user_json = _user_json(target)
    resp = JSONResponse(user_json)
    secure = APP_ENV != "development"
    resp.set_cookie(key="session", value=new_token, max_age=30*86400, httponly=True, samesite="lax", path="/", secure=secure)
    resp.set_cookie(key="csrf_token", value=generate_csrf_token(target.id), max_age=3600, httponly=False, samesite="lax", path="/", secure=secure)
    return resp
