from app.models import Post

def _get_descendant_ids(session, current_id, current_depth=0, max_depth=5, collected=None):
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
