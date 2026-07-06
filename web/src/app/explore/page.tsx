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

function ExploreFallback() {
  return <div className="empty-state">로딩 중...</div>;
}

function ExploreContent() {
  const router = useRouter();
  const [posts, setPosts] = useState<PostData[]>([]);
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [inputValue, setInputValue] = useState("");
  const [searched, setSearched] = useState(false);
  const [fetchedUrl, setFetchedUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchParams = useSearchParams();

  const loadExplore = useCallback(() => {
    setLoading(true); setSearched(false); setFetchedUrl(null);
    api.explore().then((d) => { setPosts(d.posts); setNovels(d.novels); setUsers([]); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) { loadExplore(); return; }
    setLoading(true); setSearched(true); setFetchedUrl(null);
    try {
      const res = await api.search(q.trim());
      setPosts(res.posts);
      setNovels(res.novels);
      setUsers(res.users);
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

  useEffect(() => {
    const urlParam = searchParams.get("url");
    const qParam = searchParams.get("q");
    if (urlParam) {
      setInputValue(urlParam);
      handleUrlFetch(urlParam);
    } else if (qParam) {
      setInputValue(qParam);
      doSearch(qParam);
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
    doSearch(q);
  };

  return (
    <div className="explore-page-layout">
      <div className="explore-page-top">
        <h3 className="section-header hm-bottom-8"><Icon name="buildings" /> 지금 우리 서버는...</h3>
        <form className="explore-search" onSubmit={handleSubmit}>
          <span className="explore-search-icon" onClick={(ev) => { const f = (ev.target as HTMLElement).closest('form'); if (f) f.requestSubmit(); }}>
            <Icon name="search" size={14} />
          </span>
          <input ref={inputRef} type="text" name="q" placeholder="검색..." className="explore-search-input" value={inputValue} onChange={e => setInputValue(e.target.value)} />
          {inputValue && (
              <span className="explore-search-clear" onClick={() => { setInputValue(""); loadExplore(); }}>
              <Icon name="x" size={14} />
            </span>
          )}
        </form>
        {!loading && !searched && novels.length > 0 && (
          <div className="explore-series-section">
            <h4 className="section-header explore-section-title-sm"><Icon name="book" /> 최신 시리즈</h4>
            <div className="explore-series-wrap">
            <div className="explore-series-scroll">
              {novels.slice(0, 6).map((n) => (
                <div key={n.id} className="explore-series-card" onClick={() => router.push(`/series/${n.id}`)}>
                  <div className="explore-series-cover">
                    {n.cover_image ? (
                      <img src={n.cover_image} alt={n.title} className="cover-img" />
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
      {loading ? (
        <>
          {posts.length === 0 && novels.length === 0 && users.length === 0 ? (
            <div className="empty-state">검색 결과가 없습니다.</div>
          ) : (
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
                              <img src={n.cover_image} alt={n.title} className="cover-img" />
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
                              <span><Icon name={n.is_completed ? "check" : "edit"} /> {n.is_completed ? "완결" : "연재중"}</span>
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
                          <strong>{u.display_name}</strong>
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
      ) : posts.length === 0 ? (
        <div className="empty-state">게시글이 없습니다.</div>
      ) : (
        posts.map((p) => <PostCard key={p.id} post={p} />)
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
