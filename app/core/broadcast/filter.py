def _should_deliver_fast(user_id: int, tl_type: str, author_id: int, visibility: str,
                         follower_ids: set[int], author_is_local: bool,
                         mentioned_ids: list[int] | None = None) -> bool:
    mentioned_set = set(mentioned_ids) if mentioned_ids else set()
    if tl_type == "home":
        if user_id == author_id:
            return True
        if user_id in mentioned_set:
            return True
        if visibility in ("public", "home", "followers"):
            return user_id in follower_ids
        return False
    if tl_type == "social":
        if user_id == author_id:
            return True
        if user_id in mentioned_set:
            return True
        if visibility == "public":
            return user_id in follower_ids or user_id == author_id or author_is_local
        if visibility in ("home", "followers"):
            return user_id in follower_ids
        return False
    if tl_type == "local":
        return visibility == "public" and author_is_local
    return visibility == "public"
