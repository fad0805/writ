"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import { hashColor } from "@/lib/avatar";

export default function NovelsPage() {
  const router = useRouter();
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getNovels().then((d) => { setNovels(d.novels); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-header">
        <h2><Icon name="books" /> 모든 시리즈</h2>
      </div>
      <div className="novel-grid">
        {loading ? (
          <p className="empty-state">로딩 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">아직 등록된 시리즈가 없습니다.</p>
        ) : novels.map((n) => (
          <div key={n.id} className="novel-card" onClick={() => router.push(`/series/@${n.author?.username}/${n.number}`)} style={{ cursor: "pointer" }}>
            <div className="novel-card-body" style={{ display: "flex", gap: 14 }}>
              <div style={{ width: 80, aspectRatio: "3/4", borderRadius: 6, flexShrink: 0, overflow: "hidden" }}>
                {n.cover_image ? (
                  <img src={n.cover_image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <div style={{ width: "100%", height: "100%", backgroundColor: hashColor(n.title), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "1.5em", fontWeight: "bold" }}>
                    <Icon name="book" size={24} />
                  </div>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <h3 style={{ fontSize: "1em", marginBottom: 4 }}>{n.title}</h3>
                <p className="novel-author" style={{ marginBottom: 6 }}>
                  by <span onClick={(e) => { e.stopPropagation(); router.push(`/@${n.author?.username}`); }} style={{ color: "var(--accent)", cursor: "pointer" }}>{n.author?.display_name || n.author?.username}</span>
                </p>
                <p className="novel-desc" style={{ marginBottom: 6 }}>{(n.description || "").slice(0, 120)}{n.description && n.description.length > 120 ? "..." : ""}</p>
                <div className="novel-meta">
                  <span><Icon name="book" /> {n.episode_count}화</span>
                  <span><Icon name={n.is_completed ? "check" : "edit"} /> {n.is_completed ? "완결" : "연재중"}</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
