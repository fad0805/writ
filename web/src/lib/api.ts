async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function formRequest<T>(path: string, data: Record<string, any>): Promise<T> {
  const form = new FormData();
  for (const [k, v] of Object.entries(data)) {
    if (v !== undefined && v !== null) form.append(k, String(v));
  }
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  avatar: string;
  summary: string;
  is_admin: boolean;
  is_remote: boolean;
  is_locked?: boolean;
  role?: string;
  default_visibility?: string;
  series_default_visibility?: string;
  episode_default_visibility?: string;
}

export interface PostData {
  id: number;
  number: string;
  ap_id: string;
  content: string;
  summary: string;
  visibility: string;
  created_at: string | null;
  author: User;
  likes_count: number;
  boosts_count: number;
  replies_count: number;
  liked: boolean;
  boosted: boolean;
  bookmarked: boolean;
  is_mine: boolean;
  reply_context: ReplyContext | null;
  replies?: PostData[];
  ancestors?: PostData[];
  boosted_by?: User | null;
}

export interface ReplyContext {
  id: number;
  number: string;
  content: string;
  author: User;
  visibility: string;
}

export interface NotificationData {
  id: number;
  type: string;
  created_at: string | null;
  is_read: boolean;
  from_user: User | null;
  post: PostData | null;
}

export interface NovelData {
  id: number;
  number: string;
  title: string;
  description: string;
  cover_image: string;
  tags: string;
  is_completed: boolean;
  is_published: boolean;
  episode_count: number;
  total_views: number;
  visibility: string;
  created_at: string | null;
  updated_at: string | null;
  author: User | null;
  author_id: number;
}

export interface SearchResults {
  posts: PostData[];
  novels: NovelData[];
  users: User[];
}

export interface EpisodeData {
  id: number;
  novel_id: number;
  episode_number: number;
  title: string;
  content: string;
  summary: string;
  comment: string;
  views: number;
  is_published: boolean;
  created_at: string | null;
  updated_at: string | null;
}

// Auth
export const api = {
  me: () => request<User>("/api/auth/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  // Timeline
  timeline: (type: string = "home", limit: number = 10, offset: number = 0) =>
    request<{ posts: PostData[]; timeline_type: string; has_more: boolean }>(
      `/api/timeline/${type}?limit=${limit}&offset=${offset}`
    ),

  // Posts
  getPost: (id: number, reply_offset = 0, reply_limit = 5) =>
    request<PostData & { total_replies: number; has_more_replies: boolean }>(
      `/api/posts/${id}?reply_offset=${reply_offset}&reply_limit=${reply_limit}`
    ),
  createPost: (data: { content: string; summary?: string; visibility?: string; parent_id?: number; share_url?: string }) =>
    formRequest<PostData>("/api/posts", data),
  editPost: (id: number, data: { content: string; summary?: string }) =>
    formRequest<PostData>(`/api/posts/${id}/edit`, data),
  deletePost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/delete`, { method: "POST" }),
  like: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/like`, { method: "POST" }),
  unlike: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/unlike`, { method: "POST" }),
  boost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/boost`, { method: "POST" }),
  unboost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/unboost`, { method: "POST" }),
  bookmark: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/bookmark`, { method: "POST" }),
  unbookmark: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/unbookmark`, { method: "POST" }),
  getBookmarks: () => request<{ posts: PostData[] }>("/api/bookmarks"),

  // Users
  getProfile: (username: string) =>
    request<{
      profile: User;
      posts: PostData[];
      novels: NovelData[];
      followers: { user: User }[];
      following: { user: User }[];
      followers_count: number;
      following_count: number;
      is_following: boolean;
      is_follow_pending: boolean;
      has_pending_follower: boolean;
      is_follower: boolean;
      is_mine: boolean;
    }>(`/api/users/${username}`),
  follow: (username: string) => request<{ ok: boolean }>(`/api/users/${username}/follow`, { method: "POST" }),
  unfollow: (username: string) => request<{ ok: boolean }>(`/api/users/${username}/unfollow`, { method: "POST" }),
  getFollowers: (username: string) => request<{ users: User[] }>(`/api/users/${username}/followers`),
  getFollowing: (username: string) => request<{ users: User[] }>(`/api/users/${username}/following`),

  // Notifications
  getNotifications: (filter?: string) =>
    request<{ notifications: NotificationData[] }>(
      `/api/notifications${filter ? `?filter_type=${filter}` : ""}`
    ),

  // Novels
  getNovels: () => request<{ novels: NovelData[] }>("/api/novels"),
  getMyNovels: () => request<{ novels: NovelData[] }>("/api/novels/my"),
  getNovel: (id: number) => request<{ novel: NovelData; episodes: EpisodeData[]; author: User; is_mine: boolean }>(`/api/novels/${id}`),
  deleteNovel: (id: number) => request<{ ok: boolean }>(`/api/novels/${id}/delete`, { method: "POST" }),
  getEpisode: (id: number, eid: number) => request<{
    episode: EpisodeData; novel: NovelData; is_mine: boolean;
    prev_episode: EpisodeData | null; next_episode: EpisodeData | null;
  }>(`/api/novels/${id}/episodes/${eid}`),

  // Explore
  explore: () => request<{ posts: PostData[]; novels: NovelData[] }>("/api/explore"),
  search: (q: string) => request<SearchResults>(`/api/search?q=${encodeURIComponent(q)}`),
  autocomplete: (q: string) => request<{ users: User[] }>(`/api/users/autocomplete?q=${encodeURIComponent(q)}`),

  // Auth actions
  login: async (username: string, password: string) => {
    const form = new FormData();
    form.append("username", username);
    form.append("password", password);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || "Login failed");
    }
    return { ok: true };
  },
  register: async (username: string, password: string, display_name?: string) => {
    const form = new FormData();
    form.append("username", username);
    form.append("password", password);
    if (display_name) form.append("display_name", display_name);
    const res = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || "Registration failed");
    }
    return { ok: true };
  },
};
