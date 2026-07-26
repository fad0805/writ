import json
import datetime
import logging

from typing import Optional

from app.config.settings import BASE_URL
from app.db.database import get_session
from app.models import User, Post, Follow
from app.utils.to_ap_serializer import to_ap_note, to_ap_create

logger = logging.getLogger("writ.activitypub")


def get_outbox(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        query = session.query(Post).filter(
            Post.author_id == user.id,
            Post.is_deleted == False,
            Post.novel_id.is_(None),
            Post.visibility.in_(["public", "unlisted", "home"]),
        ).order_by(Post.created_at.desc())

        total = query.count()
        outbox_url = user.outbox_uri()
        if page is not None:
            offset = (page - 1) * 20
            posts = query.offset(offset).limit(20).all()
            items = [to_ap_create(p) for p in posts]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{outbox_url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": outbox_url,
                "orderedItems": items,
                "next": f"{outbox_url}?page={page + 1}" if offset + 20 < total else None,
                "prev": f"{outbox_url}?page={page - 1}" if page > 1 else None,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": outbox_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{outbox_url}?page=1",
            }


def get_followers(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        if user.follow_list_visibility == "private":
            return {"@context": "https://www.w3.org/ns/activitystreams", "id": user.followers_uri(), "type": "OrderedCollection", "totalItems": 0, "first": f"{user.followers_uri()}?page=1"}

        query = session.query(Follow).filter(
            Follow.following_id == user.id,
            Follow.accepted == True,
        )

        total = query.count()
        url = user.followers_uri()

        if page is not None:
            offset = (page - 1) * 20
            follows = query.offset(offset).limit(20).all()
            items = [f.follower.actor_uri() for f in follows]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": url,
                "orderedItems": items,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{url}?page=1",
            }


def get_following(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None

        if user.follow_list_visibility == "private":
            return {"@context": "https://www.w3.org/ns/activitystreams", "id": user.following_uri(), "type": "OrderedCollection", "totalItems": 0, "first": f"{user.following_uri()}?page=1"}

        query = session.query(Follow).filter(
            Follow.follower_id == user.id,
            Follow.accepted == True,
        )

        total = query.count()
        url = user.following_uri()

        if page is not None:
            offset = (page - 1) * 20
            follows = query.offset(offset).limit(20).all()
            items = [f.following.actor_uri() for f in follows]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": url,
                "orderedItems": items,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{url}?page=1",
            }


def get_featured(username: str, page: Optional[int] = None):
    with get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            return None
        pinned_ids = user.pinned_posts or []
        if not pinned_ids:
            featured_url = user.featured_uri()
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": featured_url,
                "type": "OrderedCollection",
                "totalItems": 0,
                "first": f"{featured_url}?page=1",
            }

        posts = session.query(Post).filter(
            Post.id.in_(pinned_ids),
            Post.is_deleted == False,
        ).all()
        posts_dict = {p.id: p for p in posts}
        ordered = [posts_dict[pid] for pid in pinned_ids if pid in posts_dict]

        featured_url = user.featured_uri()
        total = len(ordered)
        if page is not None:
            offset = (page - 1) * 20
            page_posts = ordered[offset:offset + 20]
            items = [to_ap_note(p) for p in page_posts]
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{featured_url}?page={page}",
                "type": "OrderedCollectionPage",
                "totalItems": total,
                "partOf": featured_url,
                "orderedItems": items,
                "next": f"{featured_url}?page={page + 1}" if offset + 20 < total else None,
                "prev": f"{featured_url}?page={page - 1}" if page > 1 else None,
            }
        else:
            return {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": featured_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{featured_url}?page=1",
            }
