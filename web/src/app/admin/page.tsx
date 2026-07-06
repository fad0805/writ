"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import { CustomEmoji, invalidateEmojiCache } from "@/lib/emojis";

export default function AdminPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [emojis, setEmojis] = useState<CustomEmoji[]>([]);
  const [emojiKeyword, setEmojiKeyword] = useState("");
  const [emojiCategory, setEmojiCategory] = useState("");
  const [emojiAliases, setEmojiAliases] = useState("");
  const [emojiFile, setEmojiFile] = useState<File | null>(null);
  const [emojiSubmitting, setEmojiSubmitting] = useState(false);
  const [emojiFilter, setEmojiFilter] = useState("all");
  const [emojiSearch, setEmojiSearch] = useState("");
  const [showUpload, setShowUpload] = useState(false);

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    fetch("/api/emojis", { credentials: "include" })
      .then(r => r.json()).then(setEmojis).catch(() => {});
  }, []);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>

      <div className="hm-bottom-28">
        <h3 className="hm-bottom-16" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => setShowUpload(!showUpload)}>
          <Icon name="smile" /> 커스텀 이모지 <span style={{ fontSize: "0.7em", color: "var(--text-muted)" }}>{showUpload ? "▲" : "▼"}</span>
        </h3>

        {showUpload && <form onSubmit={async (e) => {
          e.preventDefault();
          if (emojiSubmitting || !emojiFile) return;
          setEmojiSubmitting(true);
          try {
            const form = new FormData();
            form.append("keyword", emojiKeyword);
            form.append("category", emojiCategory);
            form.append("aliases", emojiAliases);
            form.append("image", emojiFile);
            const res = await fetch("/api/emojis", { method: "POST", credentials: "include", body: form });
            if (res.ok) {
              const newEmoji = await res.json();
              setEmojis([...emojis, newEmoji]);
              setEmojiKeyword(""); setEmojiCategory(""); setEmojiAliases(""); setEmojiFile(null);
              invalidateEmojiCache();
            } else {
              const d = await res.json();
              alert(d.detail || "업로드 실패");
            }
          } catch { alert("업로드 실패"); }
          setEmojiSubmitting(false);
        }} className="novel-form">
          <div className="form-group">
            <label>키워드 <small>(:keyword:)</small></label>
            <input type="text" value={emojiKeyword} onChange={(e) => setEmojiKeyword(e.target.value.replace(/[^a-z0-9_]/gi, "_").toLowerCase())} placeholder="blobcat" required className="cw-input w-full" />
          </div>
          <div className="form-group">
            <label>카테고리</label>
            <input type="text" value={emojiCategory} onChange={(e) => setEmojiCategory(e.target.value)} placeholder="기본" className="cw-input w-full" />
          </div>
          <div className="form-group">
            <label>별칭 <small>(쉼표로 구분)</small></label>
            <input type="text" value={emojiAliases} onChange={(e) => setEmojiAliases(e.target.value)} placeholder="blob, blob_cat" className="cw-input w-full" />
          </div>
          <div className="form-group">
            <label>이미지</label>
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(e) => setEmojiFile(e.target.files?.[0] || null)} required className="mt-4" />
          </div>
          <div className="form-actions">
            <button type="submit" disabled={emojiSubmitting || !emojiFile || !emojiKeyword.trim()} className="btn btn-primary">업로드</button>
          </div>
        </form>}

        <div className="hm-top-24">
          <input type="text" value={emojiSearch} onChange={(e) => setEmojiSearch(e.target.value)} placeholder="이모지 검색..." className="cw-input w-full hm-bottom-8" />
          <div className="flex-row gap-8 mb-12">
            {["all", "local", "remote"].map((f) => (
              <button key={f} onClick={() => setEmojiFilter(f)} className={`btn btn-small ${emojiFilter === f ? "btn-primary" : "btn-outline"}`}>{f === "all" ? "전체" : f === "local" ? "로컬" : "리모트"}</button>
            ))}
          </div>
          {emojis.length === 0 ? (
            <p className="empty-state">등록된 커스텀 이모지가 없습니다.</p>
          ) : (
            <div className="flex-col gap-8">
              {emojis.filter(e => (emojiFilter === "all" || (emojiFilter === "local" ? e.category !== "remote" : e.category === "remote")) && (!emojiSearch || e.keyword.includes(emojiSearch.toLowerCase()))).map((emo) => (
                <div key={emo.id} className="emoji-list-item">
                  <img src={emo.url} alt={emo.keyword} width={33} height={33} className="emoji-img-admin" />
                  <div className="emoji-info">
                    <div className="emoji-keyword">:<span className="emoji-accent">{emo.keyword}</span>:</div>
                    <div className="emoji-meta">
                      {emo.category && <span>#{emo.category}</span>}
                      {emo.aliases && emo.aliases.length > 0 && <span> {emo.aliases.map((a: string) => `:${a}:`).join(" ")}</span>}
                    </div>
                  </div>
                  {emo.category === "remote" && (
                    <button type="button" onClick={async () => {
                      const form = new FormData(); form.append("category", "기본");
                      const res = await fetch(`/api/emojis/${emo.id}`, { method: "PATCH", credentials: "include", body: form });
                      if (res.ok) {
                        const d = await res.json();
                        setEmojis(emojis.map(e => e.id === emo.id ? d.emoji : e));
                        invalidateEmojiCache();
                      }
                    }} className="btn" style={{ fontSize: "0.85em", color: "var(--accent)", border: "1px solid var(--border)", padding: "4px 12px" }}>복사</button>
                  )}
                  <button type="button" onClick={async () => {
                    if (!confirm(`:${emo.keyword}:를 삭제하시겠습니까?`)) return;
                    try {
                      const res = await fetch(`/api/emojis/${emo.id}`, { method: "DELETE", credentials: "include" });
                      if (res.ok) { setEmojis(emojis.filter(e => e.id !== emo.id)); invalidateEmojiCache(); }
                    } catch {}
                  }} className="btn emoji-delete-btn">삭제</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
