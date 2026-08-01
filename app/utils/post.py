import re

from app.models import Post, Tag


def _sync_post_tags(post, s):
    """Parse #hashtags from post content and sync with Tag model."""
    tags = set(re.findall(r'(?<!\w)#([\w_가-힣]+)', post.content))
    desired = {t.lower(): t for t in tags}
    current = {t.name: t for t in (post.tag_list or [])}
    for lower_name, display in desired.items():
        if lower_name in current:
            tag = current[lower_name]
            if tag.display_name != display:
                tag.display_name = display
        else:
            tag = s.query(Tag).filter_by(name=lower_name).first()
            if not tag:
                tag = Tag(name=lower_name, display_name=display)
                s.add(tag)
                s.flush()
            else:
                tag.display_name = display
            post.tag_list.append(tag)
    for name in set(current.keys()) - set(desired.keys()):
        tag = current[name]
        post.tag_list.remove(tag)


def _get_descendant_ids(session, current_id, current_depth=0, max_depth=20, collected=None):
    if collected is None:
        collected = set()
    if current_depth >= max_depth:
        return collected

    child_ids = [
        r[0] for r in session.query(Post.id).filter(
        Post.in_reply_to_id == current_id, Post.is_deleted == False
        ).all()
    ]

    for cid in child_ids:
        if cid not in collected:
            collected.add(cid)
            _get_descendant_ids(session, cid, current_depth + 1, max_depth, collected)
    return collected
