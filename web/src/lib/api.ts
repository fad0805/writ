function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const method = (options?.method || "GET").toUpperCase();
    const headers: Record<string, string> = { "Content-Type": "application/json", ...options?.headers as Record<string, string> };
    if (method !== "GET" && method !== "HEAD") {
      const csrf = getCsrfToken();
      if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    const res = await fetch(path, {
      credentials: "include",
      headers,
      ...options,
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || `HTTP ${res.status}`);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function formRequest<T>(path: string, data: Record<string, any>): Promise<T> {
  const form = new FormData();
  for (const [k, v] of Object.entries(data)) {
    if (v !== undefined && v !== null) form.append(k, String(v));
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const csrf = getCsrfToken();
    const headers: Record<string, string> = {};
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const res = await fetch(path, {
      method: "POST",
      credentials: "include",
      body: form,
      headers,
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || `HTTP ${res.status}`);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  avatar: string;
  header?: string;
  summary: string;
  is_admin: boolean;
  is_remote: boolean;
  is_locked?: boolean;
  is_limited?: boolean;
  is_frozen?: boolean;
  is_deceased?: boolean;
  email?: string;
  email_verified?: boolean;
  role?: string;
  default_visibility?: string;
  episode_default_visibility?: string;
  display_handle?: string;
  follow_list_visibility?: string;
  aliases?: string[];
  moved_to?: string;
  pinned_posts?: number[];
  pinned_series?: number[];
  enable_reactions?: boolean;
  remote_url?: string;
}

export interface PollOption {
  text: string;
  votes_count: number;
}

export interface PollData {
  options: PollOption[];
  expires_at: string | null;
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
  is_dm?: boolean;
  is_following_author?: boolean;
  reply_context: ReplyContext | null;
  replies?: PostData[];
  ancestors?: PostData[];
  boosted_by?: User | null;
  poll_data?: PollData | null;
  my_vote?: number | null;
  reactions?: Record<string, number>;
  my_reaction?: string | null;
  mentioned_handles?: string[];
  link_preview?: { url: string; title: string; description: string; image: string } | null;
  is_deleted?: boolean;
  quote_of_id?: number | null;
  quote_of_ap_id?: string;
  _emojis?: { keyword: string; file_name: string; url: string; aliases: string[] }[];
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
  metadata?: Record<string, any>;
}

export interface NovelData {
  id: number;
  number: string;
  title: string;
  description: string;
  cover_image: string;
  tags: string;
  status: string;
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
  blocked_domain?: string;
}

export interface NoticeData {
  id: number;
  uuid: string;
  novel_id: number;
  title: string;
  content: string;
  is_pinned: boolean;
  created_at: string | null;
  updated_at: string | null;
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
    request<{ posts: PostData[]; timeline_type: string; has_more: boolean; _emojis?: any[] }>(
      `/api/timeline/${type}?limit=${limit}&offset=${offset}`
    ),

  // Posts
  getPost: (id: number, reply_offset = 0, reply_limit = 5) =>
    request<PostData & { total_replies: number; has_more_replies: boolean }>(
      `/api/posts/${id}?reply_offset=${reply_offset}&reply_limit=${reply_limit}`
    ),
  createPost: (data: { content: string; summary?: string; visibility?: string; parent_id?: number; share_url?: string; media_attachments?: string; is_sensitive?: boolean; poll_options?: string; poll_expires_in?: number; link_preview?: string }) =>
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
  getBookmarks: (limit = 20, offset = 0) => request<{ posts: PostData[]; has_more: boolean }>(`/api/bookmarks?limit=${limit}&offset=${offset}`),
  getFavorites: (limit = 10, offset = 0) => request<{ posts: PostData[]; has_more: boolean }>(`/api/favorites?limit=${limit}&offset=${offset}`),
  vote: (id: number, option: number) => formRequest<{ ok: boolean; post?: PostData }>(`/api/posts/${id}/vote`, { option }),
  unvote: (id: number) => formRequest<{ ok: boolean }>(`/api/posts/${id}/unvote`, {}),
  react: (id: number, emoji: string) => formRequest<{ ok: boolean }>(`/api/posts/${id}/react`, { emoji }),
  unreact: (id: number) => formRequest<{ ok: boolean }>(`/api/posts/${id}/unreact`, {}),

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
      notify_on_post: boolean;
      has_pending_follower: boolean;
      is_follower: boolean;
      is_mine: boolean;
    }>(`/api/users/${username}`),
  follow: (username: string) => request<{ ok: boolean }>(`/api/users/${username}/follow`, { method: "POST" }),
  unfollow: (username: string) => request<{ ok: boolean }>(`/api/users/${username}/unfollow`, { method: "POST" }),
  toggleNotify: (username: string) => request<{ ok: boolean; notify_on_post: boolean }>(`/api/users/${username}/toggle-notify`, { method: "POST" }),
  getFollowers: (username: string) => request<{ users: User[] }>(`/api/users/${username}/followers`),
  getFollowing: (username: string) => request<{ users: User[] }>(`/api/users/${username}/following`),

  // Notifications
  getNotifications: (filter?: string, limit = 20, offset = 0, mark_read = true) =>
    request<{ notifications: NotificationData[]; has_more: boolean; total: number }>(
      `/api/notifications?limit=${limit}&offset=${offset}&mark_read=${mark_read}${filter ? `&filter_type=${filter}` : ""}`
    ),

  // Novels
  getNovels: (limit = 12, offset = 0) => request<{ novels: NovelData[]; has_more: boolean }>(`/api/series?limit=${limit}&offset=${offset}`),
  getMyNovels: (limit = 12, offset = 0) => request<{ novels: NovelData[]; total: number; page: number; pages: number }>(`/api/series/my?limit=${limit}&offset=${offset}`),
  getFollowedNovels: (limit = 12, offset = 0) => request<{ novels: NovelData[]; total: number; page: number; pages: number }>(`/api/series/followed?limit=${limit}&offset=${offset}`),
  getNovel: (id: number) => request<{ novel: NovelData; episodes: EpisodeData[]; author: User; is_mine: boolean; is_following: boolean }>(`/api/series/${id}`),
  deleteNovel: (id: number) => request<{ ok: boolean }>(`/api/series/${id}/delete`, { method: "POST" }),
  getEpisode: (id: number, eid: number) => request<{
    episode: EpisodeData; novel: NovelData; is_mine: boolean;
    prev_episode: EpisodeData | null; next_episode: EpisodeData | null;
  }>(`/api/series/${id}/episodes/${eid}`),

  // Notices
  getNotices: (novel_id: number) => request<NoticeData[]>(`/api/series/${novel_id}/notices`),

  // Reports
  report: (target_type: string, target_id: number, reason: string, rule_ids?: number[]) =>
    formRequest<{ ok: boolean; report_id: number }>("/api/reports", { target_type, target_id, reason, rule_ids: rule_ids ? JSON.stringify(rule_ids) : "" }),

  // Explore
  explore: (limit = 20, offset = 0) => request<{ posts: PostData[]; novels: NovelData[]; has_more: boolean }>(`/api/explore?limit=${limit}&offset=${offset}`),
  search: (q: string, author?: string) => request<SearchResults>(`/api/search?q=${encodeURIComponent(q)}${author ? `&author=${encodeURIComponent(author)}` : ""}`),
  autocomplete: (q: string) => request<{ users: User[] }>(`/api/search/users?q=${encodeURIComponent(q)}`),

  // Auth actions
  login: async (username: string, password: string) => {
    const params = new URLSearchParams();
    params.append("username", username);
    params.append("password", password);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || "Login failed");
    }
    return { ok: true };
  },
  register: async (username: string, password: string, email: string, display_name?: string) => {
    const form = new FormData();
    form.append("username", username);
    form.append("password", password);
    form.append("email", email);
    if (display_name) form.append("display_name", display_name);
    const res = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || "Registration failed");
    }
    return res.json();
  },
  verifyEmail: async (token: string) => {
    const form = new FormData();
    form.append("token", token);
    const res = await fetch("/api/auth/verify-email", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || "Email verification failed");
    }
    return res.json();
  },
  resendVerification: async (email: string) => {
    const form = new FormData();
    form.append("email", email);
    const res = await fetch("/api/auth/resend-verification", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.error || "Failed to resend verification email");
    }
    return res.json();
  },
  forgotPassword: async (email: string) => {
    const form = new FormData();
    form.append("email", email);
    const res = await fetch("/api/auth/forgot-password", { method: "POST", credentials: "include", body: form });
    if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || "전송 실패"); }
    return res.json();
  },
  resetPassword: async (token: string, password: string) => {
    const form = new FormData();
    form.append("token", token);
    form.append("password", password);
    const res = await fetch("/api/auth/reset-password", { method: "POST", credentials: "include", body: form });
    if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || "리셋 실패"); }
    return res.json();
  },
  fetchLinkPreview: (url: string) =>
    formRequest<{ url: string; title: string; description: string; image: string }>("/api/link-preview", { url }),
};
