"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";
import { api } from "@/lib/api";

interface EpisodeItem {
  id: number; title: string; number: number; is_published: boolean; created_at: string;
}

interface AdminNovel {
  id: number; title: string; number: string; author_id: number; visibility: string;
  is_published: boolean; is_sensitive: boolean; episode_count: number; episodes: EpisodeItem[];
}

interface AdminUser {
  id: number; username: string; display_name: string; avatar: string; role: string;
}

export default function AdminContentPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [query, setQuery] = useState("");
  const [targetUser, setTargetUser] = useState<AdminUser | null>(null);
  const [novels, setNovels] = useState<AdminNovel[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedNovel, setExpandedNovel] = useState<number | null>(null);

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const handleSearch = async () => {
    const cleaned = query.trim();
    if (!cleaned) return;
    setLoading(true);
    try {
      let uid: number;
      if (/^\d+$/.test(cleaned)) {
        uid = parseInt(cleaned, 10);
      } else {
        const userRes = await fetch(`/api/profile/${encodeURIComponent(cleaned.replace(/^@/, ""))}`, { credentials: "include" });
        if (!userRes.ok) { alert("사용자를 찾을 수 없습니다."); setLoading(false); return; }
        const userData = await userRes.json();
        uid = userData.profile.id;
        setTargetUser(userData.profile);
      }
      const res = await fetch(`/api/admin/users/${uid}/novels`, { credentials: "include" });
      if (!res.ok) { alert("시리즈를 불러올 수 없습니다."); setLoading(false); return; }
      const data = await res.json();
      setTargetUser(data.user);
      setNovels(data.novels);
    } catch { alert("오류가 발생했습니다."); }
    setLoading(false);
  };

  const toggleSensitive = async (novelId: number) => {
    const res = await fetch(`/api/admin/novels/${novelId}/toggle-sensitive`, { method: "POST", credentials: "include" });
    if (!res.ok) { alert("실패했습니다."); return; }
    const data = await res.json();
    setNovels(novels.map(n => n.id === novelId ? { ...n, is_sensitive: data.is_sensitive } : n));
  };

  const setVisibility = async (novelId: number, visibility: string) => {
    const fd = new FormData();
    fd.append("visibility", visibility);
    const res = await fetch(`/api/admin/novels/${novelId}/set-visibility`, { method: "POST", credentials: "include", body: fd });
    if (!res.ok) { alert("실패했습니다."); return; }
    const data = await res.json();
    setNovels(novels.map(n => n.id === novelId ? { ...n, visibility: data.visibility, is_published: visibility !== "private" } : n));
  };

  const togglePublish = async (episodeId: number) => {
    const res = await fetch(`/api/admin/episodes/${episodeId}/toggle-publish`, { method: "POST", credentials: "include" });
    if (!res.ok) { alert("실패했습니다."); return; }
    const data = await res.json();
    setNovels(novels.map(n => ({
      ...n,
      episodes: n.episodes.map(ep => ep.id === episodeId ? { ...ep, is_published: data.is_published } : ep)
    })));
  };

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="book" /> 콘텐츠 관리</h2>
      </div>
      <AdminNav current="content" />

      <div className="form-group">
        <label>유저 검색 (사용자명 또는 ID)</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="사용자명 또는 @username" className="form-input" style={{ flex: 1 }} />
          <button onClick={handleSearch} disabled={loading} className="btn btn-primary">검색</button>
        </div>
      </div>

      {targetUser && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, padding: 12, background: "var(--bg-secondary)", borderRadius: 8 }}>
          {targetUser.avatar ? <img src={targetUser.avatar} alt="" style={{ width: 36, height: 36, borderRadius: "50%", objectFit: "cover" }} /> : <Icon name="user" />}
          <div>
            <strong>{targetUser.display_name || targetUser.username}</strong>
            <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 6 }}>@{targetUser.username}</span>
          </div>
        </div>
      )}

      {loading && <p className="empty-state">로딩 중...</p>}

      {novels.map(n => (
        <div key={n.id} style={{ padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <strong>{n.title}</strong>
              <span style={{ marginLeft: 8, fontSize: 12, color: "var(--text-muted)" }}>
                #{n.number} · {n.episode_count}화 · {n.visibility}
              </span>
            </div>
            <span className={`badge ${n.is_sensitive ? "badge-danger" : "badge-default"}`}>
              {n.is_sensitive ? "민감" : "일반"}
            </span>
            <button onClick={() => toggleSensitive(n.id)} className="btn btn-small btn-outline">
              민감 전환
            </button>
            <div className="visibility-selector-inline">
              <select value={n.visibility} onChange={(e) => setVisibility(n.id, e.target.value)}
                style={{ fontSize: 12, padding: "3px 6px", borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg)" }}>
                <option value="public">전체공개</option>
                <option value="unlisted">공개</option>
                <option value="private">비공개</option>
              </select>
            </div>
            <button onClick={() => setExpandedNovel(expandedNovel === n.id ? null : n.id)} className="btn btn-small btn-outline">
              <Icon name={expandedNovel === n.id ? "chevron_up" : "chevron_down"} />
            </button>
          </div>
          {expandedNovel === n.id && (
            <div style={{ marginTop: 12, paddingLeft: 16 }}>
              {n.episodes.length === 0 && <p style={{ fontSize: 13, color: "var(--text-muted)" }}>에피소드 없음</p>}
              {n.episodes.map(ep => (
                <div key={ep.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", fontSize: 13 }}>
                  <span style={{ flex: 1 }}>#{ep.number} {ep.title}</span>
                  <span className={`badge ${ep.is_published ? "badge-success" : "badge-muted"}`}>
                    {ep.is_published ? "공개" : "비공개"}
                  </span>
                  <button onClick={() => togglePublish(ep.id)} className="btn btn-small btn-outline">
                    {ep.is_published ? "비공개로" : "공개로"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {!loading && targetUser && novels.length === 0 && <p className="empty-state">시리즈가 없습니다.</p>}
    </>
  );
}
