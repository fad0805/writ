"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

interface EpisodeItem {
  id: number; title: string; number: number; is_published: boolean; created_at: string; novel_id: number;
}

interface AdminNovel {
  id: number; title: string; number: string; author_id: number; visibility: string;
  is_published: boolean; is_sensitive: boolean; episode_count: number; episodes: EpisodeItem[];
  author: { id: number; username: string; display_name: string; avatar: string } | null;
}

export default function AdminContentPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [query, setQuery] = useState("");
  const [novels, setNovels] = useState<AdminNovel[]>([]);
  const [results, setResults] = useState<{ novels: AdminNovel[]; episodes: EpisodeItem[] }>({ novels: [], episodes: [] });
  const [loading, setLoading] = useState(false);
  const [expandedNovel, setExpandedNovel] = useState<number | null>(null);
  const [searchMode, setSearchMode] = useState<"series" | "episode">("series");

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  const handleSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/content/search?q=${encodeURIComponent(q)}&mode=${searchMode}`, { credentials: "include" });
      if (!res.ok) { alert("검색 실패"); setLoading(false); return; }
      const data = await res.json();
      setResults({ novels: data.novels || [], episodes: data.episodes || [] });
      setNovels(data.novels || []);
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
    setNovels(novels.map(n => n.id === novelId ? { ...n, visibility, is_published: visibility !== "private" } : n));
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

  const deleteEpisode = async (episode: EpisodeItem) => {
    if (!confirm(`에피소드 "${episode.title}"(#${episode.number})를 삭제하시겠습니까?`)) return;
    const res = await fetch(`/api/series/${episode.novel_id}/episodes/${episode.id}/delete`, { method: "POST", credentials: "include" });
    if (!res.ok) { alert("삭제 실패"); return; }
    setNovels(novels.map(n => ({
      ...n,
      episodes: n.episodes.filter(ep => ep.id !== episode.id),
      episode_count: n.episode_count - 1,
    })));
    setResults(prev => ({ ...prev, episodes: prev.episodes.filter(ep => ep.id !== episode.id) }));
  };

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="book" /> 서버 관리</h2>
      </div>
      <AdminNav current="content" />

      <div className="form-group">
        <label>시리즈 / 에피소드 검색</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="제목으로 검색" className="form-input" style={{ flex: 1 }} />
          <button onClick={handleSearch} disabled={loading} className="btn btn-primary">검색</button>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
            <input type="radio" name="mode" value="series" checked={searchMode === "series"} onChange={() => setSearchMode("series")} /> 시리즈
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, cursor: "pointer" }}>
            <input type="radio" name="mode" value="episode" checked={searchMode === "episode"} onChange={() => setSearchMode("episode")} /> 에피소드
          </label>
        </div>
      </div>

      {loading && <p className="empty-state">로딩 중...</p>}

      {searchMode === "series" && novels.map(n => (
        <div key={n.id} style={{ padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <strong>{n.title}</strong>
              <span style={{ marginLeft: 8, fontSize: 12, color: "var(--text-muted)" }}>
                #{n.number} · {n.episode_count}화 · {n.visibility}
                {n.author && <> · {n.author.display_name || n.author.username}</>}
              </span>
            </div>
            <span className={`badge ${n.is_sensitive ? "badge-danger" : "badge-default"}`}>
              {n.is_sensitive ? "민감" : "일반"}
            </span>
            <button onClick={() => toggleSensitive(n.id)} className="btn btn-small btn-outline">
              민감 전환
            </button>
            <select value={n.visibility} onChange={(e) => setVisibility(n.id, e.target.value)}
              style={{ fontSize: 12, padding: "3px 6px", borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg)" }}>
              <option value="public">전체공개</option>
              <option value="unlisted">공개</option>
              <option value="private">비공개</option>
            </select>
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
                  <button onClick={() => deleteEpisode(ep)} className="btn btn-small" style={{ color: "var(--danger)" }}>
                    삭제
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}

      {searchMode === "episode" && results.episodes.length > 0 && (
        <div>
          {results.episodes.map(ep => (
            <div key={ep.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0", borderBottom: "1px solid var(--border)", fontSize: 13 }}>
              <span style={{ flex: 1 }}>
                <strong>{ep.title}</strong>
                <span style={{ marginLeft: 8, color: "var(--text-muted)" }}>#{ep.number}</span>
              </span>
              <span className={`badge ${ep.is_published ? "badge-success" : "badge-muted"}`}>
                {ep.is_published ? "공개" : "비공개"}
              </span>
              <button onClick={() => togglePublish(ep.id)} className="btn btn-small btn-outline">
                {ep.is_published ? "비공개로" : "공개로"}
              </button>
              <button onClick={() => deleteEpisode(ep)} className="btn btn-small" style={{ color: "var(--danger)" }}>
                삭제
              </button>
            </div>
          ))}
        </div>
      )}

      {!loading && query && ((searchMode === "series" && novels.length === 0) || (searchMode === "episode" && results.episodes.length === 0)) && (
        <p className="empty-state">검색 결과가 없습니다.</p>
      )}
    </>
  );
}
