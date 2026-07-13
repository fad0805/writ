"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, NovelData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";
import ClickableCover from "@/components/ClickableCover";
import InfiniteScroll from "@/components/InfiniteScroll";

export default function NovelsPage() {
  const { user } = useAuth();
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
      if (Math.abs(dx) > 60 && dx > 0) router.push("/series/my");
    };
    document.addEventListener("touchend", h, { passive: true });
    return () => document.removeEventListener("touchend", h);
  }, [router]);
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [offset, setOffset] = useState(12);

  useEffect(() => {
    api.getNovels(12, 0).then((d) => { setNovels(d.novels); setHasMore(d.has_more); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const d = await api.getNovels(6, offset);
      setNovels((prev) => { const merged = [...prev, ...d.novels]; if (merged.length >= 200) setHasMore(false); return merged; });
      setHasMore(d.has_more);
      setOffset((prev) => prev + 6);
    } catch {}
    setLoadingMore(false);
  }, [offset, hasMore, loadingMore]);

  const card = (n: NovelData) => (
    <div key={n.id} className="novel-card novel-card-clickable" onClick={() => router.push(`/series/@${n.author?.username}/${n.number}`)}>
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
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="page-header">
        <h2><Icon name="books" /> 모든 시리즈</h2>
      </div>
      {user && (
        <div className="series-filter-tabs">
          <Link href="/series/my" className="series-filter-tab">내 시리즈</Link>
          <Link href="/series" className="series-filter-tab active">모든 시리즈</Link>
        </div>
      )}
      <div className="novel-grid">
        {loading ? (
          <p className="empty-state">로딩 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">아직 등록된 시리즈가 없습니다.</p>
        ) : (
          <InfiniteScroll hasMore={hasMore} loadingMore={loadingMore} loadMore={loadMore}>
            {novels.map(card)}
          </InfiniteScroll>
        )}
      </div>
    </>
  );
}
