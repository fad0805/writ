"""Boost pointer grouping and booster list merging."""


def _aggregate_boost_groups(feed_dicts):
    """4. 중복된 부스트 포인터들을 그룹화하고 부스터 목록 병합"""
    groups: dict[int, dict] = {}
    order: list[int] = []

    for d in feed_dicts:
        if not d:
            continue
        key = d.get("boost_of_id") or d["id"]
        if key not in groups:
            groups[key] = d
            order.append(key)
        else:
            existing = groups[key]
            if (d.get("created_at") or "") > (existing.get("created_at") or ""):
                groups[key] = d
                existing = d

            existing_boosted_by = existing.get("boosted_by") or []
            d_boosted_by = d.get("boosted_by") or []
            seen_ids = {b["id"] for b in existing_boosted_by if b}
            merged = list(existing_boosted_by)
            for b in d_boosted_by:
                if b and b["id"] not in seen_ids:
                    seen_ids.add(b["id"])
                    merged.append(b)
            existing["boosted_by"] = merged

    return [groups[k] for k in order]
