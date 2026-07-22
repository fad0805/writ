"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData } from "@/lib/api";
import Icon from "@/components/Icon";
import Link from "next/link";
import ClickableCover from "@/components/ClickableCover";
import { hashColor } from "@/lib/avatar";

export default function FollowedNovelsPage() {
  const router = useRouter();
  const touchStartX = useRef(0);

  useEffect(() => {
    const h = (e: TouchEvent) => { touchStartX.current = e.touches[0].clientX; };
    document.addEventListener("touchstart", h, { passive: true });
    return () => document.removeEventListener("touchstart", h);
  }, []);

  useEffect(() => {
    const h = (e: TouchEvent) => {
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 120 && dx < 0) router.push("/series");
      if (Math.abs(dx) > 120 && dx > 0) router.push("/series/my");
    };
    document.addEventListener("touchend", h, { passive: true });
    return () => document.removeEventListener("touchend", h);
  }, [router]);

  const [novels, setNovels] = useState<NovelData[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const d = await api.getFollowedNovels(12, (p - 1) * 12);
      setNovels(d.novels);
      setPage(d.page);
      setPages(d.pages);
      setTotal(d.total);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(1); }, [load]);

  const handleUnfollow = async (e: React.MouseEvent, novelId: number) => {
    e.stopPropagation();
    if (!confirm("구독을 해제하시겠습니까?")) return;
    try {
      await fetch(`/api/series/${novelId}/unfollow`, { method: "POST", credentials: "include" });
      setNovels((prev) => prev.filter((n) => n.id !== novelId));
      setTotal((prev) => prev - 1);
    } catch {}
  };

  const card = (n: NovelData) => (
    <div key={n.id} className="novel-card novel-card-clickable" onClick={() => router.push(`/series/@${n.author?.username || ''}/${n.number}`)}>
      <div className="novel-card-body novel-card-body-flex">
        <div className="cover-wrap-80">
          {n.cover_image ? (
            <ClickableCover src={n.cover_image} isSensitive={(n as any).is_sensitive} className="cover-img" />
          ) : (
            <div className="cover-fallback cover-fallback-lg" style={{ backgroundColor: hashColor(n.title) }}>
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
            <span><Icon name={({ ongoing: "edit", hiatus: "moon", discontinued: "x", completed: "check" } as Record<string,string>)[n.status] || "edit"} /> {({ ongoing: "연재중", hiatus: "휴재", discontinued: "연재중단", completed: "완결" } as Record<string,string>)[n.status] || "연재중"}</span>
            <span><Icon name="users" /> {(n as any).followers_count || 0}</span>
          </div>
          <div className="novel-actions my-series-actions">
            <button className="btn btn-small btn-danger op-70" onClick={(e) => handleUnfollow(e, n.id)}>구독 해제</button>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="page-header">
        <h2><Icon name="bookmark" /> 구독 시리즈</h2>
      </div>
      <div className="series-filter-tabs">
        <Link href="/series/my" className="series-filter-tab">내 시리즈</Link>
        <Link href="/series/followed" className="series-filter-tab active">구독 시리즈</Link>
        <Link href="/series" className="series-filter-tab">모든 시리즈</Link>
      </div>
      <div className="novel-grid">
        {loading ? (
          <p className="empty-state">로딩 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">구독한 시리즈가 없습니다.</p>
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
