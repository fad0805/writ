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
}

export interface PostData {
  id: number;
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
  is_mine: boolean;
  reply_context: ReplyContext | null;
  replies?: PostData[];
  ancestors?: PostData[];
  boosted_by?: User | null;
}

export interface ReplyContext {
  id: number;
  content: string;
  author: User;
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
  title: string;
  description: string;
  tags: string;
  is_completed: boolean;
  is_published: boolean;
  episode_count: number;
  created_at: string | null;
  updated_at: string | null;
  author_id: number;
}

export interface EpisodeData {
  id: number;
  novel_id: number;
  episode_number: number;
  title: string;
  content: string;
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
  getPost: (id: number) => request<PostData>(`/api/posts/${id}`),
  createPost: (data: { content: string; summary?: string; visibility?: string; parent_id?: number }) =>
    formRequest<PostData>("/api/posts", data),
  editPost: (id: number, data: { content: string; summary?: string }) =>
    formRequest<PostData>(`/api/posts/${id}/edit`, data),
  deletePost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/delete`, { method: "POST" }),
  like: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/like`, { method: "POST" }),
  unlike: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/unlike`, { method: "POST" }),
  boost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/boost`, { method: "POST" }),
  unboost: (id: number) => request<{ ok: boolean }>(`/api/posts/${id}/unboost`, { method: "POST" }),

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

  // Explore
  explore: () => request<{ posts: PostData[] }>("/api/explore"),

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
