"""Federation broadcast for newly created posts."""
import re
import logging
import httpx

from app.models import User, Post, Follow
from app.utils.to_ap_serializer import to_ap_create
from app.core.activitypub import broadcast_to_followers, _post_to_inbox, _resolve_actor
from app.core.federation import federation_allowed
from app.db.database import get_session

logger = logging.getLogger(__name__)


def _broadcast_federation(user_id, post_id, visibility, plain_content=''):
    with get_session() as ap_s:
        user = ap_s.query(User).filter_by(id=user_id).first()
        post = ap_s.query(Post).filter_by(id=post_id).first()
        if not user or not post:
            logger.warning(f"Broadcast aborted: user_id={user_id} or post_id={post_id} not found")
            return

        create_activity = to_ap_create(post)

        inboxes = set()
        if visibility == "mention":
            if post.mentioned_user_ids:
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    inbox = mu.inbox_url
                    if inbox:
                        inboxes.add(inbox)
        else:
            if post.in_reply_to_id and post.parent:
                parent_author = post.parent.author
                if parent_author and parent_author.is_remote:
                    inbox = parent_author.inbox_url
                    if inbox:
                        inboxes.add(inbox)
                elif parent_author and not parent_author.is_remote:
                    pf_follows = ap_s.query(Follow).filter(
                        Follow.following_id == parent_author.id,
                        Follow.follower.has(is_remote=True),
                    ).all()
                    for pf in pf_follows:
                        inbox = pf.follower.shared_inbox_url or pf.follower.inbox_url
                        if inbox:
                            inboxes.add(inbox)

            if post.mentioned_user_ids:
                follower_ids = {f.following_id for f in ap_s.query(Follow).filter(
                    Follow.following_id == user.id,
                    Follow.follower.has(is_remote=True),
                ).all()} if post.mentioned_user_ids else set()
                mu_users = ap_s.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mu_users:
                    if mu.id not in follower_ids:
                        inbox = mu.inbox_url
                        if inbox:
                            inboxes.add(inbox)
    for inbox in inboxes:
        _post_to_inbox(inbox, create_activity, user)

    broadcast_to_followers(user, create_activity)

    if visibility != "mention":
        remote_handles = set(re.findall(r'@([a-zA-Z0-9_]+@[\w.-]+\.[a-zA-Z]{2,})', plain_content or ""))
        for handle in remote_handles:
            with get_session() as s:
                remote_user = s.query(User).filter(
                    User.username == handle, User.is_remote == True
                ).first()
            if remote_user:
                inbox = remote_user.inbox_url
                if inbox:
                    _post_to_inbox(inbox, create_activity, user)
                continue
            try:
                r_name, r_domain = handle.split("@", 1)
                if not federation_allowed(r_domain):
                    continue
                resolved = None
                for url in [f"https://{r_domain}/@{r_name}", f"https://{r_domain}/users/{r_name}"]:
                    try:
                        resolved = _resolve_actor(url, sign_as=user)
                        if resolved:
                            break
                    except Exception:
                        continue
                if not resolved:
                    wf = httpx.get(
                        f"https://{r_domain}/.well-known/webfinger?resource=acct:{handle}",
                        timeout=5,
                    )
                    if wf.status_code == 200:
                        for link in wf.json().get("links", []):
                            if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                href = link.get("href", "")
                                if href:
                                    resolved = _resolve_actor(href, sign_as=user)
                                    break
                if resolved:
                    with get_session() as s:
                        remote_user = s.query(User).get(resolved.id)
                    if remote_user:
                        inbox = remote_user.inbox_url
                        if inbox:
                            _post_to_inbox(inbox, create_activity, user)
            except Exception:
                pass
