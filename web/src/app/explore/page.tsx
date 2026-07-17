"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import { api, PostData, NovelData, User } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";
import Avatar from "@/components/Avatar";
import { useSearchParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { Suspense } from "react";
import { useAuth } from "@/lib/auth";
import ClickableCover from "@/components/ClickableCover";
import { getCustomEmojis, renderCustomEmojis, CustomEmoji } from "@/lib/emojis";
import { sanitizeName } from "@/lib/sanitize";

function ExploreFallback() {
  return <div className="empty-state">로딩 중...</div>;
}

function ExploreContent() {
  const { user } = useAuth();
  const router = useRouter();
  const [posts, setPosts] = useState<PostData[]>([]);
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [searched, setSearched] = useState(false);
  const [fetchedUrl, setFetchedUrl] = useState<string | null>(null);
  const [blockedDomain, setBlockedDomain] = useState<string | null>(null);
  const [emojiMap, setEmojiMap] = useState<CustomEmoji[]>([]);
  const [searchAuthor, setSearchAuthor] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const exploreOffsetRef = useRef(0);
  const searchParams = useSearchParams();

  const loadExplore = useCallback(() => {
    setLoading(true); setSearched(false); setFetchedUrl(null); exploreOffsetRef.current = 0;
    api.explore(20, 0).then((d) => { setPosts(d.posts); setNovels(d.novels); setHasMore(d.has_more); setUsers([]); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const loadMoreExplore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    exploreOffsetRef.current += 20;
    try {
      const d = await api.explore(5, exploreOffsetRef.current);
      setPosts((prev) => { const ids = new Set(prev.map((p) => p.id)); return [...prev, ...d.posts.filter((p: any) => !ids.has(p.id))]; });
      setHasMore(d.has_more);
    } catch {}
    setLoadingMore(false);
  }, [loadingMore, hasMore]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => { if (entries[0].isIntersecting) loadMoreExplore(); },
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMoreExplore]);

  const doSearch = useCallback(async (q: string, author?: string) => {
    if (!q.trim()) { loadExplore(); return; }
    const match = q.match(/(^|>|\s)@([a-zA-Z][a-zA-Z0-9]*(?:@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})?)/g);
    if (match) {
      const form = new FormData(); form.append("url", `https://${match[2]}/users/${match[1]}`);
      try {
        const res = await fetch("/api/fetch-actor", { method: "POST", credentials: "include", body: form });
        if (res.ok) {
          const d = await res.json();
          window.location.href = `/profile/${d.username}`;
          return;
        }
      } catch {}
    }
    setLoading(true); setSearched(true); setFetchedUrl(null); setBlockedDomain(null);
    try {
      const res = await api.search(q.trim(), author);
      setPosts(res.posts);
      setNovels(res.novels);
      setUsers(res.users);
      if (res.blocked_domain) setBlockedDomain(res.blocked_domain);
    } catch { setPosts([]); setNovels([]); setUsers([]); }
    setLoading(false);
  }, [loadExplore]);

  const handleUrlFetch = useCallback(async (url: string) => {
    setLoading(true); setSearched(true); setFetchedUrl(null);
    try {
      const form = new FormData();
      form.append("url", url);
      const res = await fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form });
      if (res.ok) {
        const post: PostData = await res.json();
        setPosts([post]);
        setNovels([]);
        setUsers([]);
        setFetchedUrl(url);
      } else { const text = await res.text().catch(() => ""); alert("불러오기 실패: " + text.slice(0, 100)); setPosts([]); setNovels([]); setUsers([]); }
    } catch (e: unknown) { alert("불러오기 실패: " + ((e instanceof Error ? e.message : "") || "")); setPosts([]); setNovels([]); setUsers([]); }
    setLoading(false);
  }, []);

  useEffect(() => { getCustomEmojis().then(setEmojiMap); }, []);

  useEffect(() => {
    const urlParam = searchParams.get("url");
    const qParam = searchParams.get("q");
    const authorParam = searchParams.get("author");
    if (urlParam) {
      setInputValue(urlParam);
      handleUrlFetch(urlParam);
    } else if (qParam) {
      setInputValue(qParam);
      setSearchAuthor(authorParam || "");
      doSearch(qParam, authorParam || undefined);
    } else {
      loadExplore();
    }
  }, [searchParams, loadExplore, doSearch, handleUrlFetch]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = inputRef.current?.value.trim() || "";
    if (!q) { loadExplore(); return; }
    if (q.startsWith("http")) {
      handleUrlFetch(q);
      return;
    }
    // @username@domain 형식 → 원격 유저 검색
    const match = q.match(/^@?(\w+)@([\w.-]+)$/);
    if (match) {
      setLoading(true); setSearched(true); setPosts([]); setNovels([]); setUsers([]);
      const form = new FormData(); form.append("url", `https://${match[2]}/users/${match[1]}`);
      try {
        const res = await fetch("/api/fetch-actor", { method: "POST", credentials: "include", body: form });
        if (res.ok) {
          const d = await res.json();
          window.location.href = `/profile/${d.username}`;
          return;
        }
      } catch {}
      setInputValue(q);
      doSearch(q);
      return;
    }
    doSearch(q);
  };

  return (
    <div className="explore-page-layout">
      <div className="explore-page-top">
        <h3 className="section-header hm-bottom-8"><Icon name="buildings" /> 지금 우리 서버는...</h3>
        {user && <form className="explore-search" onSubmit={handleSubmit}>
          <span className="explore-search-icon" onClick={(ev) => { const f = (ev.target as HTMLElement).closest('form'); if (f) f.requestSubmit(); }}>
            <Icon name="search" size={14} />
          </span>
          <input ref={inputRef} type="text" name="q" placeholder="검색..." className="explore-search-input" value={inputValue} onChange={e => setInputValue(e.target.value)} />
          {inputValue && (
              <span className="explore-search-clear" onClick={() => { setInputValue(""); loadExplore(); }}>
              <Icon name="x" size={14} />
            </span>
          )}
        </form>}
        {!loading && !searched && novels.length > 0 && (
          <div className="explore-series-section">
            <h4 className="section-header explore-section-title-sm"><Icon name="book" /> 최신 시리즈</h4>
            <div className="explore-series-wrap">
            <div className="explore-series-scroll">
              {novels.slice(0, 6).map((n) => (
                <div key={n.id} className="explore-series-card" onClick={() => router.push(`/series/${n.id}`)}>
                  <div className="explore-series-cover">
                    {n.cover_image ? (
                      <ClickableCover src={n.cover_image} isSensitive={(n as any).is_sensitive} className="cover-img" />
                    ) : (
                      <div className="cover-fallback cover-fallback-md" style={{ backgroundColor: hashColor(n.title) }}>
                        {n.title[0]}
                      </div>
                    )}
                  </div>
                  <div className="explore-series-info">
                    <strong>{n.title}</strong>
                    <span>by. {n.author?.display_name || n.author?.username || ""}</span>
                    <span>제{n.episode_count}화</span>
                  </div>
                </div>
              ))}
            </div>
            </div>
          </div>
        )}
      </div>
      {blockedDomain && (
        <div style={{ marginBottom: 12, padding: "8px 12px", background: "var(--danger-bg, #fff3cd)", border: "1px solid var(--danger, #ffc107)", borderRadius: 6, color: "var(--danger-text, #856404)", fontSize: "0.9em" }}>
          <Icon name="ban" /> <strong>{blockedDomain}</strong> 서버는 연합이 차단되어 있습니다.
        </div>
      )}
      {loading && !searched ? (
        <div className="empty-state">로딩 중...</div>
      ) : posts.length === 0 && novels.length === 0 && users.length === 0 ? (
        <div className="empty-state">검색 결과가 없습니다.</div>
      ) : (
        <>
          {!loading && !searched && posts.length > 0 && (
            <>{posts.map((p) => <PostCard key={p.id} post={p} />)}<div ref={sentinelRef} />{loadingMore && <p className="empty-state">불러오는 중...</p>}</>
          )}
          {user && searched && (
            <>
              {fetchedUrl && posts.length > 0 && (
                <>
                  <h4 className="search-section-title">
                    <Icon name="globe" /> 리모트 게시글
                    <span className="fetched-url-label">{fetchedUrl}</span>
                  </h4>
                  {posts.map((p) => <PostCard key={p.id} post={p} />)}
                </>
              )}
              {!fetchedUrl && posts.length > 0 && (
                <>
                  <h4 className="search-section-title"><Icon name="globe" /> 게시글</h4>
                  {posts.map((p) => <PostCard key={p.id} post={p} />)}
                </>
              )}
              {novels.length > 0 && (
                <>
                  <h4 className="search-section-title"><Icon name="book" /> 시리즈</h4>
                  <div className="novel-grid">
                    {novels.map((n) => (
                      <div key={n.id} className="novel-card novel-card-clickable" onClick={() => window.location.href = `/series/${n.id}`}>
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
                              by <a href={`/@${n.author?.username}`} onClick={(e) => e.stopPropagation()} className="novel-card-author">{n.author?.display_name || n.author?.username}</a>
                            </p>
                            <p className="novel-desc novel-card-desc">{(n.description || "").slice(0, 120)}{n.description && n.description.length > 120 ? "..." : ""}</p>
                            <div className="novel-meta">
                              <span><Icon name="book" /> {n.episode_count}화</span>
                              <span><Icon name={({ ongoing: "edit", hiatus: "moon", discontinued: "x", completed: "check" } as Record<string,string>)[n.status] || "edit"} /> {({ ongoing: "연재중", hiatus: "휴재", discontinued: "연재중단", completed: "완결" } as Record<string,string>)[n.status] || "연재중"}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {users.length > 0 && (
                <>
                  <h4 className="search-section-title"><Icon name="users" /> 사용자</h4>
                  <div className="user-search-list">
                    {users.map((u) => (
                      <Link key={u.id} href={`/@${u.username}`} className="user-search-card">
                        <Avatar user={u} className="sidebar-avatar rounded-[8px]" style={{ width: 36, height: 36, minWidth: 36 }} />
                        <div>
                          <strong dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(u.display_name, emojiMap, 14)) }} />
                          <span>@{u.username}</span>
                        </div>
                      </Link>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default function ExplorePageWrapper() {
  return (
    <Suspense fallback={<ExploreFallback />}>
      <ExploreContent />
    </Suspense>
  );
}
