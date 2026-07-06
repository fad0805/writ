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
          <div key={n.id} className="novel-card novel-card-clickable" onClick={() => router.push(`/series/@${n.author?.username}/${n.number}`)}>
            <div className="novel-card-body novel-card-body-flex">
              <div className="cover-wrap-80">
                {n.cover_image ? (
                  <img src={n.cover_image} alt="" className="cover-img" />
                ) : (
                  <div className="cover-fallback" style={{ backgroundColor: hashColor(n.title), fontSize: "1.5em" }}>
                    <Icon name="book" size={24} />
                  </div>
                )}
              </div>
              <div className="novel-card-body-content">
                <h3 className="novel-card-title">{n.title}</h3>
                <p className="novel-author novel-card-author-wrap">
                  by <span onClick={(e) => { e.stopPropagation(); router.push(`/@${n.author?.username}`); }} className="novel-card-author cursor-pointer">{n.author?.display_name || n.author?.username}</span>
                </p>
                <p className="novel-desc novel-card-desc">{(n.description || "").slice(0, 120)}{n.description && n.description.length > 120 ? "..." : ""}</p>
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
