"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import { api, PostData, NovelData, User } from "@/lib/api";
import PostCard from "@/components/PostCard";
import Icon from "@/components/Icon";
import Link from "next/link";
import { hashColor } from "@/lib/avatar";
import Avatar from "@/components/Avatar";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function ExploreFallback() {
  return <div className="empty-state">로딩 중...</div>;
}

function ExploreContent() {
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
    api.explore().then((d) => { setPosts(d.posts); setNovels([]); setUsers([]); setLoading(false); }).catch(() => setLoading(false));
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
    <>
      <h3 className="section-header"><Icon name="buildings" /> 지금 우리 서버는...</h3>
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
      {loading ? (
        <div className="empty-state">로딩 중...</div>
      ) : searched ? (
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
                      <div key={n.id} className="novel-card" onClick={() => window.location.href = `/series/${n.id}`} style={{ cursor: "pointer" }}>
                        <div className="novel-card-body" style={{ display: "flex", gap: 14 }}>
                          <div style={{ width: 80, aspectRatio: "3/4", borderRadius: 6, flexShrink: 0, overflow: "hidden" }}>
                            {n.cover_image ? (
                              <img src={n.cover_image} alt={n.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                            ) : (
                              <div style={{ width: "100%", height: "100%", backgroundColor: hashColor(n.title), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: "1.5em", fontWeight: "bold" }}>
                                <Icon name="book" size={24} />
                              </div>
                            )}
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <h3 style={{ fontSize: "1em", marginBottom: 4 }}>{n.title}</h3>
                            <p className="novel-author" style={{ marginBottom: 6 }}>
                              by <a href={`/@${n.author?.username}`} onClick={(e) => e.stopPropagation()} style={{ color: "var(--accent)" }}>{n.author?.display_name || n.author?.username}</a>
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
              )}
              {users.length > 0 && (
                <>
                  <h4 className="search-section-title"><Icon name="users" /> 사용자</h4>
                  <div className="user-search-list">
                    {users.map((u) => (
                      <Link key={u.id} href={`/@${u.username}`} className="user-search-card">
                        <Avatar user={u} className="sidebar-avatar rounded-[8px]" style={{ width: 36, height: 36, minWidth: 36, borderRadius: 8, fontSize: 16 }} />
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
    </>
  );
}

export default function ExplorePageWrapper() {
  return (
    <Suspense fallback={<ExploreFallback />}>
      <ExploreContent />
    </Suspense>
  );
}
