from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import desc

from models import Novel, Episode, Post, User, get_session
from routes.auth import require_auth, get_current_user
from activitypub import broadcast_to_followers, _post_to_inbox
from routes.sns import _icon, parse_mentions, _sidebar, _right_sidebar
from config import BASE_URL

router = APIRouter()

NOVEL_VISIBILITY_LABELS = {
    "public": "전체공개",
    "unlisted": "공개",
    "private": "비공개",
}


def _can_view_novel(novel, user):
    return novel.visibility != "private" or novel.author_id == user.id


def _novel_visibility_label(novel):
    visibility = getattr(novel, "visibility", None) or ("public" if novel.is_published else "private")
    return NOVEL_VISIBILITY_LABELS.get(visibility, "전체공개")


def _novel_visibility_selector(current="public"):
    return f'''<div class="visibility-selector novel-visibility-selector">
      <label><input type="radio" name="visibility" value="public" {"checked" if current == "public" else ""}>{_icon("globe")} 전체공개</label>
      <label><input type="radio" name="visibility" value="unlisted" {"checked" if current == "unlisted" else ""}>{_icon("eye")} 공개</label>
      <label><input type="radio" name="visibility" value="private" {"checked" if current == "private" else ""}>{_icon("lock")} 비공개</label>
    </div>
    <p class="form-help">전체공개는 모든 소설 목록에 노출되고, 공개는 작가 프로필과 URL로만 접근할 수 있습니다.</p>'''



@router.get("/novels", response_class=HTMLResponse)
def novel_list(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        novels = session.query(Novel).filter_by(is_published=True, visibility="public").order_by(
            desc(Novel.updated_at)
        ).limit(50).all()

    return HTMLResponse(render_novel_list(user, novels))


@router.get("/novels/my", response_class=HTMLResponse)
def my_novels(request: Request):
    user = require_auth(request)

    with get_session() as session:
        novels = session.query(Novel).filter_by(author_id=user.id).order_by(
            desc(Novel.updated_at)
        ).all()

    return HTMLResponse(render_my_novels(user, novels))


@router.get("/novels/new", response_class=HTMLResponse)
def new_novel_page(request: Request):
    user = require_auth(request)
    return HTMLResponse(render_new_novel(user))


@router.post("/novels/new")
def create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                 tags: str = Form(""), visibility: str = Form("public")):
    user = require_auth(request)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"

    with get_session() as session:
        novel = Novel(
            author_id=user.id,
            title=title,
            description=description,
            tags=tags,
            visibility=visibility,
            is_published=visibility != "private",
        )
        session.add(novel)
        session.commit()
        return RedirectResponse(url=f"/novels/{novel.id}", status_code=303)


@router.get("/novels/{novel_id}", response_class=HTMLResponse)
def novel_detail(request: Request, novel_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if not _can_view_novel(novel, user):
            raise HTTPException(status_code=403, detail="이 소설을 볼 수 없습니다")

        episode_query = session.query(Episode).filter_by(novel_id=novel.id)
        if novel.author_id != user.id:
            episode_query = episode_query.filter_by(is_published=True)
        episodes = episode_query.order_by(Episode.episode_number).all()

    return HTMLResponse(render_novel_detail(user, novel, episodes))


@router.get("/novels/{novel_id}/edit", response_class=HTMLResponse)
def edit_novel_page(request: Request, novel_id: int):
    user = require_auth(request)

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")

    return HTMLResponse(render_edit_novel(user, novel))


@router.post("/novels/{novel_id}/edit")
def edit_novel(request: Request, novel_id: int, title: str = Form(...),
               description: str = Form(""), tags: str = Form(""),
               is_completed: bool = Form(False), visibility: str = Form("public")):
    user = require_auth(request)

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if visibility not in ("public", "unlisted", "private"):
            visibility = "public"

        novel.title = title
        novel.description = description
        novel.tags = tags
        novel.is_completed = is_completed
        novel.visibility = visibility
        novel.is_published = visibility != "private"
        session.commit()

    return RedirectResponse(url=f"/novels/{novel_id}", status_code=303)


@router.post("/novels/{novel_id}/delete")
def delete_novel(request: Request, novel_id: int):
    user = require_auth(request)

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        session.delete(novel)
        session.commit()

    return RedirectResponse(url="/novels/my", status_code=303)


@router.get("/novels/{novel_id}/episodes/new", response_class=HTMLResponse)
def new_episode_page(request: Request, novel_id: int):
    user = require_auth(request)

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")

    return HTMLResponse(render_new_episode(user, novel))


@router.post("/novels/{novel_id}/episodes/new")
def create_episode(request: Request, novel_id: int, title: str = Form(...),
                   content: str = Form(...), summary: str = Form(""),
                   announce: bool = Form(False), visibility: str = Form("public")):
    user = require_auth(request)

    if not title.strip() or not content.strip():
        raise HTTPException(status_code=400, detail="Title and content are required")

    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    with get_session() as session:
        novel = session.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")

        max_ep = session.query(Episode).filter_by(novel_id=novel.id).order_by(
            desc(Episode.episode_number)
        ).first()
        next_num = (max_ep.episode_number + 1) if max_ep else 1

        episode = Episode(
            novel_id=novel.id,
            episode_number=next_num,
            title=title,
            content=content,
            summary=summary,
        )
        session.add(episode)
        session.flush()

        if announce:
            post = Post(
                author_id=user.id,
                content=f'{_icon("book")} <a href="{BASE_URL}/novels/{novel.id}/episodes/{episode.id}">[{novel.title}] {episode.episode_number}화: {episode.title}</a>\n\n{episode.summary or ""}',
                summary=f'[소설] {novel.title} - {episode.episode_number}화',
                visibility=visibility,
                mentioned_user_ids=parse_mentions(episode.summary or ""),
                novel_id=novel.id,
                episode_id=episode.id,
            )
            session.add(post)
            session.flush()
            post.ap_id = f"{BASE_URL}/posts/{post.id}"
            episode.announcement_post_id = post.id
            session.commit()

            create_activity = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/activities/create/{post.id}",
                "type": "Create",
                "actor": user.actor_uri(),
                "object": post.to_ap_note(),
            }
            if visibility == "mention":
                if post.mentioned_user_ids:
                    mentioned_users = session.query(User).filter(
                        User.id.in_(post.mentioned_user_ids), User.is_remote == True
                    ).all()
                    for mu in mentioned_users:
                        _post_to_inbox(mu.inbox_uri(), create_activity, user)
            else:
                broadcast_to_followers(user, create_activity)
        else:
            session.commit()

    return RedirectResponse(url=f"/novels/{novel_id}", status_code=303)


@router.get("/novels/{novel_id}/episodes/{episode_id}", response_class=HTMLResponse)
def episode_detail(request: Request, novel_id: int, episode_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        episode = session.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        novel = episode.novel
        if not _can_view_novel(novel, user) or (not episode.is_published and novel.author_id != user.id):
            raise HTTPException(status_code=403, detail="이 에피소드를 볼 수 없습니다")

        # Increment view count
        episode.views += 1
        session.commit()

        prev_ep_query = session.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number < episode.episode_number,
        )
        next_ep_query = session.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number > episode.episode_number,
        )
        if novel.author_id != user.id:
            prev_ep_query = prev_ep_query.filter(Episode.is_published == True)
            next_ep_query = next_ep_query.filter(Episode.is_published == True)
        prev_ep = prev_ep_query.order_by(desc(Episode.episode_number)).first()

        next_ep = next_ep_query.order_by(Episode.episode_number).first()

    return HTMLResponse(render_episode_detail(user, novel, episode, prev_ep, next_ep))


@router.get("/novels/{novel_id}/episodes/{episode_id}/edit", response_class=HTMLResponse)
def edit_episode_page(request: Request, novel_id: int, episode_id: int):
    user = require_auth(request)

    with get_session() as session:
        episode = session.query(Episode).filter_by(
            id=episode_id, novel_id=novel_id
        ).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")

    return HTMLResponse(render_edit_episode(user, episode))


@router.post("/novels/{novel_id}/episodes/{episode_id}/edit")
def edit_episode(request: Request, novel_id: int, episode_id: int,
                 title: str = Form(...), content: str = Form(...),
                 summary: str = Form(""), is_published: bool = Form(True)):
    user = require_auth(request)

    with get_session() as session:
        episode = session.query(Episode).filter_by(
            id=episode_id, novel_id=novel_id
        ).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")

        episode.title = title
        episode.content = content
        episode.summary = summary
        episode.is_published = is_published
        session.commit()

    return RedirectResponse(url=f"/novels/{novel_id}/episodes/{episode_id}", status_code=303)


@router.post("/novels/{novel_id}/episodes/{episode_id}/delete")
def delete_episode(request: Request, novel_id: int, episode_id: int):
    user = require_auth(request)

    with get_session() as session:
        episode = session.query(Episode).filter_by(
            id=episode_id, novel_id=novel_id
        ).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")
        session.delete(episode)
        session.commit()

    return RedirectResponse(url=f"/novels/{novel_id}", status_code=303)


# ---- Render Helpers ----

def _novel_page(user, title, active_nav, content_html):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user, active_nav=active_nav)}
  <main class="main-content">
    {content_html}
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""

def render_novel_list(user, novels):
    cards = "".join(
        f'<div class="novel-card">'
        f'  <div class="novel-card-body">'
        f'    <h3><a href="/novels/{n.id}">{n.title}</a></h3>'
        f'    <p class="novel-author">by <a href="/users/{n.author.username}">{n.author.display_name or n.author.username}</a></p>'
        f'    <p class="novel-desc">{n.description[:200]}{"..." if len(n.description) > 200 else ""}</p>'
        f'    <div class="novel-meta">'
        f'      <span>{_icon("book")} {n.episode_count}화</span>'
        f'      <span>{_icon("eye")} {_novel_visibility_label(n)}</span>'
        f'      <span>{_icon("check") + " 완결" if n.is_completed else _icon("edit") + " 연재중"}</span>'
        f'      <span>{_icon("eye")} {n.total_views}</span>'
        f'    </div>'
        f'  </div>'
        f'</div>'
        for n in novels
    )

    content = f"""<div class="page-header">
      <h2>{_icon("books")} 모든 소설</h2>
      <a href="/novels/new" class="btn btn-primary">새 소설</a>
    </div>
    <div class="novel-grid">
      {cards if cards else "<p class='empty-state'>아직 등록된 소설이 없습니다.</p>"}
    </div>"""
    return _novel_page(user, "소설 목록", "all_novels", content)


def render_my_novels(user, novels):
    cards = "".join(
        f'<div class="novel-card">'
        f'  <div class="novel-card-body">'
        f'    <h3><a href="/novels/{n.id}">{n.title}</a></h3>'
        f'    <p class="novel-desc">{n.description[:200]}{"..." if len(n.description) > 200 else ""}</p>'
        f'    <div class="novel-meta">'
        f'      <span>{_icon("book")} {n.episode_count}화</span>'
        f'      <span>{_icon("eye")} {_novel_visibility_label(n)}</span>'
        f'      <span>{_icon("check") + " 완결" if n.is_completed else _icon("edit") + " 연재중"}</span>'
        f'    </div>'
        f'    <div class="novel-actions">'
        f'      <a href="/novels/{n.id}/edit" class="btn btn-small">편집</a>'
        f'      <form method="post" action="/novels/{n.id}/delete" class="inline-form">'
        f'        <button type="submit" class="btn btn-small btn-danger" onclick="return confirm(\'정말 삭제하시겠습니까?\')">삭제</button>'
        f'      </form>'
        f'    </div>'
        f'  </div>'
        f'</div>'
        for n in novels
    )

    content = f"""<div class="page-header">
      <h2>{_icon("book")} 내 소설</h2>
      <a href="/novels/new" class="btn btn-primary">새 소설</a>
    </div>
    <div class="novel-grid">
      {cards if cards else "<p class='empty-state'>아직 소설이 없습니다. <a href='/novels/new'>첫 소설을 시작해보세요!</a></p>"}
    </div>"""
    return _novel_page(user, "내 소설", "my_novels", content)


def render_new_novel(user):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>새 소설 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>새 소설 만들기</h2>
    <form method="post" action="/novels/new" class="novel-form">
      <div class="form-group">
        <label for="title">제목 *</label>
        <input type="text" id="title" name="title" required placeholder="소설 제목">
      </div>
      <div class="form-group">
        <label for="description">설명</label>
        <textarea id="description" name="description" rows="4" placeholder="소설에 대한 간단한 설명"></textarea>
      </div>
      <div class="form-group">
        <label for="tags">태그 (쉼표로 구분)</label>
        <input type="text" id="tags" name="tags" placeholder="판타지, 로맨스, SF">
      </div>
      <div class="form-group">
        <label>공개 설정</label>
        {_novel_visibility_selector("public")}
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">만들기</button>
      </div>
    </form>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_edit_novel(user, novel):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>소설 편집 - {novel.title}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>소설 편집</h2>
    <form method="post" action="/novels/{novel.id}/edit" class="novel-form">
      <div class="form-group">
        <label for="title">제목</label>
        <input type="text" id="title" name="title" value="{novel.title}" required>
      </div>
      <div class="form-group">
        <label for="description">설명</label>
        <textarea id="description" name="description" rows="4">{novel.description}</textarea>
      </div>
      <div class="form-group">
        <label for="tags">태그</label>
        <input type="text" id="tags" name="tags" value="{novel.tags}">
      </div>
      <div class="form-group">
        <label>공개 설정</label>
        {_novel_visibility_selector(getattr(novel, "visibility", None) or ("public" if novel.is_published else "private"))}
      </div>
      <div class="form-group">
        <label>
          <input type="checkbox" name="is_completed" value="true" {"checked" if novel.is_completed else ""}>
          완결
        </label>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">저장</button>
        <a href="/novels/{novel.id}" class="btn btn-outline">취소</a>
      </div>
    </form>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_novel_detail(user, novel, episodes):
    ep_list = "".join(
        f'<div class="episode-item">'
        f'  <div class="episode-number">제 {e.episode_number}화</div>'
        f'  <div class="episode-info">'
        f'    <a href="/novels/{novel.id}/episodes/{e.id}" class="episode-title">{e.title}</a>'
        f'    <div class="episode-meta">'
        f'      <span>{_icon("eye")} {e.views}</span>'
        f'      <span>{e.created_at.strftime("%Y-%m-%d")}</span>'
        f'    </div>'
        f'  </div>'
        f'</div>'
        for e in episodes
    )

    is_author = novel.author_id == user.id

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{novel.title} - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <div class="novel-header">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h2>{novel.title}</h2>
          <p class="novel-author">by <a href="/users/{novel.author.username}">{novel.author.display_name or novel.author.username}</a></p>
        </div>
        {f'''
        <div class="author-actions" style="margin-bottom:0">
          <a href="/novels/{novel.id}/edit" class="btn btn-small">소설 편집</a>
          <a href="/novels/{novel.id}/episodes/new" class="btn btn-primary btn-small">새 에피소드</a>
        </div>
        ''' if is_author else ""}
      </div>
      <div class="novel-status">
        <span>{_icon("check") + " 완결" if novel.is_completed else _icon("edit") + " 연재중"}</span>
        <span>{_icon("book")} 총 {novel.episode_count}화</span>
        <span>{_icon("eye")} 총 {novel.total_views}회 조회</span>
        <span>{_icon("eye")} {_novel_visibility_label(novel)}</span>
      </div>
      <p class="novel-description">{novel.description or ""}</p>
      {f'<p class="novel-tags">{_icon("tag")} {novel.tags}</p>' if novel.tags else ""}
    </div>

    <div class="episode-list">
      <h3>목차</h3>
      {ep_list if ep_list else "<p class='empty-state'>아직 에피소드가 없습니다.</p>"}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_new_episode(user, novel):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{novel.title}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>{novel.title}</h2>
    <form method="post" action="/novels/{novel.id}/episodes/new" class="episode-form">
      <div class="form-group">
        <label for="title">에피소드 제목</label>
        <input type="text" id="title" name="title" required placeholder="에피소드 제목">
      </div>
      <div class="form-group">
        <label for="summary">요약/스포일러 방지</label>
        <textarea id="summary" name="summary" rows="2" placeholder="에피소드 요약 (선택사항)"></textarea>
      </div>
      <div class="form-group">
        <label for="content">내용 *</label>
        <textarea id="content" name="content" rows="20" required placeholder="소설 내용을 입력하세요..."></textarea>
      </div>
      <div class="form-group announce-group">
        <label>
          <input type="checkbox" name="announce" value="true" onchange="document.getElementById('vis-selector').style.display=this.checked?'flex':'none'">
          SNS에 홍보글 게시 (ActivityPub으로 연동됨)
        </label>
        <div class="visibility-selector announce-vis" id="vis-selector" style="display:none">
          <label><input type="radio" name="visibility" value="public" checked> {_icon("globe")} 공개</label>
          <label><input type="radio" name="visibility" value="home"> {_icon("home")} 홈</label>
          <label><input type="radio" name="visibility" value="followers"> {_icon("lock")} 팔로워</label>
          <label><input type="radio" name="visibility" value="mention"> {_icon("mail")} 멘션</label>
        </div>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">게시</button>
        <a href="/novels/{novel.id}" class="btn btn-outline">취소</a>
      </div>
    </form>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_episode_detail(user, novel, episode, prev_ep, next_ep):
    prev_link = f'<a href="/novels/{novel.id}/episodes/{prev_ep.id}" class="btn btn-outline">← 이전화 ({prev_ep.title})</a>' if prev_ep else ""
    next_link = f'<a href="/novels/{novel.id}/episodes/{next_ep.id}" class="btn btn-outline">다음화 ({next_ep.title}) →</a>' if next_ep else ""

    is_author = novel.author_id == user.id

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{episode.episode_number}화 {episode.title} - {novel.title}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <div class="episode-navigation top">
      {prev_link}
      <a href="/novels/{novel.id}" class="btn btn-outline">목차</a>
      {next_link}
    </div>

    <article class="episode-content">
      <h2>제 {episode.episode_number}화: {episode.title}</h2>
      <div class="episode-meta">
        <span>{_icon("eye")} {episode.views}</span>
        <span>{episode.created_at.strftime("%Y-%m-%d %H:%M")}</span>
        {f'<span>{_icon("check") + " 공개" if episode.is_published else _icon("lock") + " 비공개"}</span>'}
      </div>
      {f'<blockquote class="episode-summary">{episode.summary}</blockquote>' if episode.summary else ""}
      <div class="episode-body">
        {episode.content.replace(chr(10), "<br>")}
      </div>
    </article>

    {f'''
    <div class="author-actions">
      <a href="/novels/{novel.id}/episodes/{episode.id}/edit" class="btn btn-small">편집</a>
      <form method="post" action="/novels/{novel.id}/episodes/{episode.id}/delete" class="inline-form">
        <button type="submit" class="btn btn-small btn-danger" onclick="return confirm('정말 삭제하시겠습니까?')">삭제</button>
      </form>
    </div>
    ''' if is_author else ""}

    <div class="episode-navigation bottom">
      {prev_link}
      <a href="/novels/{novel.id}" class="btn btn-outline">목차</a>
      {next_link}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_edit_episode(user, episode):
    novel = episode.novel
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{episode.title}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>{novel.title}</h2>
    <form method="post" action="/novels/{novel.id}/episodes/{episode.id}/edit" class="episode-form">
      <div class="form-group">
        <label for="title">에피소드 제목</label>
        <input type="text" id="title" name="title" value="{episode.title}" required>
      </div>
      <div class="form-group">
        <label for="summary">요약</label>
        <textarea id="summary" name="summary" rows="2">{episode.summary}</textarea>
      </div>
      <div class="form-group">
        <label for="content">내용</label>
        <textarea id="content" name="content" rows="20" required>{episode.content}</textarea>
      </div>
      <div class="form-group">
        <label>
          <input type="checkbox" name="is_published" value="true" {"checked" if episode.is_published else ""}>
          공개
        </label>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">저장</button>
        <a href="/novels/{novel.id}/episodes/{episode.id}" class="btn btn-outline">취소</a>
      </div>
    </form>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""
