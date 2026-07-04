import hashlib
import hmac
import time
import base64
import secrets
from fastapi import APIRouter, Request, Form, HTTPException, Response
from fastapi.responses import RedirectResponse, HTMLResponse

from models import User, get_session
from config import SECRET_KEY, SESSION_EXPIRE_DAYS
from crypto_utils import generate_keypair

router = APIRouter()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt, h.hex()


def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, h = hash_password(password, salt)
    return h == hashed


def create_session(user_id: int) -> str:
    expires = int(time.time()) + SESSION_EXPIRE_DAYS * 86400
    payload = f"{user_id}:{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        user_id = int(parts[0])
        expires = int(parts[1])
        sig = parts[2]
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}:{expires}".encode(),
                            hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected) or expires <= time.time():
            return None
    except Exception:
        return None
    with get_session() as session:
        return session.query(User).filter_by(id=user_id, is_remote=False).first()


def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    return user


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/")
    from fastapi.responses import HTMLResponse
    # Just render inline for now
    return HTMLResponse(REGISTER_PAGE)


@router.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...),
             display_name: str = Form(""), email: str = Form("")):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Username (3+) and password (6+) required")

    with get_session() as session:
        existing = session.query(User).filter_by(username=username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

        salt, pwd_hash = hash_password(password)
        priv_key, pub_key = generate_keypair()

        user = User(
            username=username,
            display_name=display_name or username,
            email=email,
            password_hash=salt + ":" + pwd_hash,
            private_key=priv_key,
            public_key=pub_key,
        )
        session.add(user)
        session.commit()

        # Set session
        token = create_session(user.id)
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(
            key="session",
            value=token,
            max_age=SESSION_EXPIRE_DAYS * 86400,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return resp


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/")
    return HTMLResponse(LOGIN_PAGE)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/")

    with get_session() as session:
        db_user = session.query(User).filter_by(username=username, is_remote=False).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        stored_hash = db_user.password_hash
        if ":" not in stored_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        salt, hash_val = stored_hash.split(":", 1)
        if not verify_password(password, salt, hash_val):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_session(db_user.id)
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(
            key="session",
            value=token,
            max_age=SESSION_EXPIRE_DAYS * 86400,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return resp


@router.post("/logout")
def logout(request: Request):
    resp = RedirectResponse(url="/login", status_code=303)
    resp.set_cookie(key="session", value="", max_age=0, path="/")
    # Clear any old DB-based session token
    user = get_current_user(request)
    if user:
        from models import get_session as gs
        with gs() as session:
            u = session.query(User).filter_by(id=user.id).first()
            if u:
                u.session_token = ""
                session.commit()
    return resp


REGISTER_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>회원가입 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="auth-container">
  <h1>회원가입</h1>
  <form method="post" action="/register">
    <div class="form-group">
      <label for="username">사용자명 *</label>
      <input type="text" id="username" name="username" required minlength="3" placeholder="3자 이상">
    </div>
    <div class="form-group">
      <label for="display_name">표시 이름</label>
      <input type="text" id="display_name" name="display_name" placeholder="프로필에 표시될 이름">
    </div>
    <div class="form-group">
      <label for="email">이메일</label>
      <input type="email" id="email" name="email" placeholder="선택사항">
    </div>
    <div class="form-group">
      <label for="password">비밀번호 *</label>
      <input type="password" id="password" name="password" required minlength="6" placeholder="6자 이상">
    </div>
    <button type="submit" class="btn btn-primary">가입하기</button>
  </form>
  <p class="auth-link">이미 계정이 있나요? <a href="/login">로그인</a></p>
</div>
<script src="/static/theme.js"></script></body>
</html>"""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>로그인 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="auth-container">
  <h1>로그인</h1>
  <form method="post" action="/login">
    <div class="form-group">
      <label for="username">사용자명</label>
      <input type="text" id="username" name="username" required>
    </div>
    <div class="form-group">
      <label for="password">비밀번호</label>
      <input type="password" id="password" name="password" required>
    </div>
    <button type="submit" class="btn btn-primary">로그인</button>
  </form>
  <p class="auth-link">계정이 없나요? <a href="/register">회원가입</a></p>
</div>
<script src="/static/theme.js"></script></body>
</html>"""
