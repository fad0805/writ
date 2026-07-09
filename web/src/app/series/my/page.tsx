"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";

export default function MyNovelsPage() {
  const router = useRouter();
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const d = await api.getMyNovels(12, (p - 1) * 12);
      setNovels(d.novels);
      setPage(d.page);
      setPages(d.pages);
      setTotal(d.total);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(1); }, [load]);

  const card = (n: NovelData) => (
    <div key={n.id} className="novel-card novel-card-clickable" onClick={() => router.push(`/series/@${n.author?.username || ''}/${n.number}`)}>
      <div className="novel-card-body novel-card-body-flex">
        <div className="cover-wrap-80">
          {n.cover_image ? (
                  <img src={n.cover_image} alt="" className="cover-img" style={(n as any).is_sensitive ? { filter: "blur(12px)" } : undefined} />
                ) : (
            <div className="cover-fallback cover-fallback-lg" style={{ backgroundColor: hashColor(n.title) }}>
              <Icon name="book" size={24} />
            </div>
          )}
        </div>
        <div className="novel-card-body-content">
          <h3 className="my-series-title-row">
            {n.title}
            <span className="my-series-vis-badge">
              {n.visibility === "public" ? "전체공개" : n.visibility === "unlisted" ? "공개" : "비공개"}
            </span>
          </h3>
          <p className="novel-desc novel-card-desc">{(n.description || "").slice(0, 120)}{n.description && n.description.length > 120 ? "..." : ""}</p>
          <div className="novel-meta my-series-meta">
            <span><Icon name="book" /> {n.episode_count}화</span>
            <span><Icon name={({ ongoing: "edit", hiatus: "moon", discontinued: "x", completed: "check" } as Record<string,string>)[n.status] || "edit"} /> {({ ongoing: "연재중", hiatus: "휴재", discontinued: "연재중단", completed: "완결" } as Record<string,string>)[n.status] || "연재중"}</span>
            <span><Icon name="eye" /> {n.total_views}</span>
          </div>
          <div className="novel-actions my-series-actions">
            <button className="btn btn-small op-70" onClick={(e) => { e.stopPropagation(); router.push(`/series/${n.id}/edit`); }}>편집</button>
            <button className="btn btn-small btn-danger op-70" onClick={async (e) => { e.stopPropagation(); if (confirm("정말 삭제하시겠습니까?")) { try { await api.deleteNovel(n.id); setNovels((prev) => prev.filter((x) => x.id !== n.id)); } catch { alert("삭제 실패"); } } }}>삭제</button>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="page-header">
        <h2><Icon name="book_solid" /> 내 시리즈</h2>
        <Link href="/series/new" className="btn btn-primary">새 시리즈</Link>
      </div>
      <div className="novel-grid">
        {loading ? (
          <p className="empty-state">로딩 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">연재 중인 시리즈가 없습니다.</p>
        ) : novels.map(card)}
      </div>
      {pages > 1 && (
        <div className="pagination">
          {Array.from({ length: pages }, (_, i) => (
            <button key={i} className={`pagination-btn${i + 1 === page ? " active" : ""}`} onClick={() => load(i + 1)}>{i + 1}</button>
          ))}
        </div>
      )}
    </>
  );
}
