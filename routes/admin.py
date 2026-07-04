from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse

from models import User, Post, Novel, Episode, get_session
from routes.auth import require_auth, get_current_user
from routes.sns import _icon

router = APIRouter()

def require_admin(request: Request):
    user = require_auth(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user

def admin_page(request: Request, title: str, content_html: str):
    user = get_current_user(request)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 관리자</title>
<link rel="stylesheet" href="/static/style.css">
<style>
.admin-layout {{ display: flex; gap: 0; height: 100vh; }}
.admin-sidebar {{ width: 220px; background: var(--bg-secondary); padding: 20px; border-right: 1px solid var(--border); display: flex; flex-direction: column; }}
.admin-sidebar h2 {{ color: var(--accent); margin-bottom: 20px; }}
.admin-sidebar a {{ display: block; padding: 8px 12px; color: var(--text-secondary); border-radius: 6px; margin-bottom: 4px; }}
.admin-sidebar a:hover {{ background: var(--border); color: var(--text-white); text-decoration: none; }}
.admin-sidebar a.active {{ background: var(--border); color: var(--accent); font-weight: 600; }}
.admin-main {{ flex: 1; padding: 30px; overflow-y: auto; background: var(--bg-primary); }}
.admin-main h1 {{ margin-bottom: 24px; color: var(--text-white); }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.stat-card {{ background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 20px; text-align: center; }}
.stat-card .stat-value {{ font-size: 2em; font-weight: bold; color: var(--accent); }}
.stat-card .stat-label {{ color: var(--text-muted); font-size: 0.85em; margin-top: 4px; }}
.admin-table {{ width: 100%; border-collapse: collapse; background: var(--bg-secondary); border-radius: 8px; overflow: hidden; }}
.admin-table th {{ background: var(--border); color: var(--text-secondary); padding: 10px 14px; text-align: left; font-weight: 600; font-size: 0.85em; }}
.admin-table td {{ padding: 10px 14px; border-top: 1px solid var(--border); color: var(--text-primary); font-size: 0.9em; }}
.admin-table tr:hover td {{ background: var(--card-hover); }}
.badge-admin {{ background: var(--accent); color: #fff; font-size: 0.75em; padding: 2px 8px; border-radius: 10px; }}
.btn-small {{ padding: 4px 12px; font-size: 0.8em; border-radius: 6px; cursor: pointer; }}
.btn-danger-small {{ background: var(--danger); color: #fff; border: none; padding: 4px 12px; font-size: 0.8em; border-radius: 6px; cursor: pointer; }}
.btn-danger-small:hover {{ background: var(--danger-hover); }}
.back-link {{ display: inline-block; margin-bottom: 20px; color: var(--text-muted); }}
.back-link:hover {{ color: var(--accent); }}
</style>
</head>
<body>
<div class="admin-layout">
  <nav class="admin-sidebar">
    <h2>⚙️ 관리자</h2>
    <a href="/admin" class="{"active" if request.url.path == "/admin" else ""}">{_icon("bar_chart")} 대시보드</a>
    <a href="/admin/users" class="{"active" if request.url.path == "/admin/users" else ""}">{_icon("users")} 사용자</a>
    <a href="/admin/posts" class="{"active" if request.url.path == "/admin/posts" else ""}">{_icon("document")} 포스트</a>
    <div style="margin-top:auto">
      <a href="/">← 사이트로 돌아가기</a>
    </div>
  </nav>
  <div class="admin-main">
    <h1>{title}</h1>
    {content_html}
  </div>
</div>
</body>
</html>""")


@router.get("/admin")
def admin_dashboard(request: Request):
    user = require_admin(request)

    with get_session() as session:
        user_count = session.query(User).count()
        remote_user_count = session.query(User).filter_by(is_remote=True).count()
        post_count = session.query(Post).filter_by(is_deleted=False).count()
        novel_count = session.query(Novel).count()
        episode_count = session.query(Episode).count()

    content = f"""
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">{user_count}</div><div class="stat-label">전체 사용자</div></div>
      <div class="stat-card"><div class="stat-value">{remote_user_count}</div><div class="stat-label">원격 사용자</div></div>
      <div class="stat-card"><div class="stat-value">{post_count}</div><div class="stat-label">포스트</div></div>
      <div class="stat-card"><div class="stat-value">{novel_count}</div><div class="stat-label">소설</div></div>
      <div class="stat-card"><div class="stat-value">{episode_count}</div><div class="stat-label">에피소드</div></div>
    </div>
    <p style="color:var(--text-muted)">관리자 대시보드에 오신 것을 환영합니다.</p>
    """
    return admin_page(request, f"{_icon('bar_chart')} 대시보드", content)


@router.get("/admin/users")
def admin_users(request: Request):
    user = require_admin(request)

    with get_session() as session:
        users = session.query(User).order_by(User.created_at.desc()).all()

    rows = "".join(
        f"<tr>"
        f"<td>{u.id}</td>"
        f"<td>{u.username} {'<span class=badge-admin>관리자</span>' if u.is_admin else ''}</td>"
        f"<td>{u.display_name or '-'}</td>"
        f"<td>{'원격' if u.is_remote else '로컬'}</td>"
        f"<td>{u.created_at.strftime('%Y-%m-%d') if u.created_at else '-'}</td>"
        f"<td>"
        f"  <form method=post action='/admin/users/{u.id}/delete' style='display:inline' onsubmit='return confirm(\"정말 삭제하시겠습니까?\")'>"
        f"    <button class='btn-danger-small'>삭제</button>"
        f"  </form>"
        f"</td>"
        f"</tr>"
        for u in users
    )

    content = f"""
    <table class="admin-table">
      <thead><tr><th>ID</th><th>사용자명</th><th>표시 이름</th><th>유형</th><th>가입일</th><th>관리</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    return admin_page(request, f"{_icon('users')} 사용자 관리", content)


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    admin = require_admin(request)
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="자기 자신을 삭제할 수 없습니다")

    with get_session() as session:
        target = session.query(User).filter_by(id=user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if target.is_admin:
            raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없습니다")
        session.delete(target)
        session.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/posts")
def admin_posts(request: Request):
    user = require_admin(request)

    with get_session() as session:
        posts = session.query(Post).filter_by(is_deleted=False).order_by(Post.created_at.desc()).limit(100).all()

    rows = "".join(
        f"<tr>"
        f"<td>{p.id}</td>"
        f"<td><a href='/users/{p.author.username}' style='color:var(--accent)'>{p.author.username}</a></td>"
        f"<td style='max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{p.content[:80]}{'...' if len(p.content)>80 else ''}</td>"
        f"<td>{p.visibility}</td>"
        f"<td>{p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '-'}</td>"
        f"<td>"
        f"  <form method=post action='/admin/posts/{p.id}/delete' style='display:inline' onsubmit='return confirm(\"정말 삭제하시겠습니까?\")'>"
        f"    <button class='btn-danger-small'>삭제</button>"
        f"  </form>"
        f"</td>"
        f"</tr>"
        for p in posts
    )

    content = f"""
    <table class="admin-table">
      <thead><tr><th>ID</th><th>작성자</th><th>내용</th><th>공개범위</th><th>작성일</th><th>관리</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    return admin_page(request, f"{_icon('document')} 포스트 관리", content)


@router.post("/admin/posts/{post_id}/delete")
def admin_delete_post(request: Request, post_id: int):
    require_admin(request)

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.is_deleted = True
        session.commit()

    return RedirectResponse(url="/admin/posts", status_code=303)
