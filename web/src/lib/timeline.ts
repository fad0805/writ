export const MAX_TL_POSTS = 300;
export const MAX_DELETED_IDS = 200;

export function capPosts<T>(posts: T[], max = MAX_TL_POSTS): T[] {
  if (posts.length <= max) return posts;
  return posts.slice(0, max);
}

export function pruneDeletedIds(ids: Set<number>, max = MAX_DELETED_IDS): Set<number> {
  if (ids.size <= max) return ids;
  for (const id of ids) {
    if (ids.size <= max) break;
    ids.delete(id);
  }
  return ids;
}