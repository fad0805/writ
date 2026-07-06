"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import Icon from "@/components/Icon";
import VisibilitySelector from "@/components/VisibilitySelector";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";
import { useAuth } from "@/lib/auth";
import { CustomEmoji, invalidateEmojiCache } from "@/lib/emojis";

export default function SettingsPage() {
  const router = useRouter();
  const { refresh: refreshAuth } = useAuth();
  const [defaultVis, setDefaultVis] = useState("public");
  const [seriesDefaultVis, setSeriesDefaultVis] = useState("public");
  const [episodeDefaultVis, setEpisodeDefaultVis] = useState("public");
  const [isLocked, setIsLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [emojis, setEmojis] = useState<CustomEmoji[]>([]);
  const [emojiKeyword, setEmojiKeyword] = useState("");
  const [emojiCategory, setEmojiCategory] = useState("");
  const [emojiAliases, setEmojiAliases] = useState("");
  const [emojiFile, setEmojiFile] = useState<File | null>(null);
  const [emojiSubmitting, setEmojiSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/emojis", { credentials: "include" })
      .then(r => r.json()).then(setEmojis).catch(() => {});
  }, []);

  useEffect(() => {
    api.me().then((u) => {
      const user = u as any;
      setDefaultVis(user.default_visibility || "public");
      setSeriesDefaultVis(user.series_default_visibility || "public");
      setEpisodeDefaultVis(user.episode_default_visibility || "public");
      setIsLocked(user.is_locked || false);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        const form = document.querySelector(".novel-form") as HTMLFormElement;
        if (form) form.requestSubmit();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("default_visibility", defaultVis);
      form.append("series_default_visibility", seriesDefaultVis);
      form.append("episode_default_visibility", episodeDefaultVis);
      form.append("is_locked", isLocked ? "true" : "");
      const res = await fetch("/api/settings/update", {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (res.ok) { await refreshAuth(); alert("저장되었습니다"); }
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 설정 관리</h2>
      </div>
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>게시글 기본 공개 설정</label>
          <VisibilitySelector value={defaultVis} onChange={(v) => setDefaultVis(v)} />
          <p className="form-help">새 게시글 작성 시 기본으로 적용될 공개 범위입니다.</p>
        </div>
        <div className="form-group">
          <label>시리즈 기본 공개 설정</label>
          <SeriesVisibilitySelector value={seriesDefaultVis} onChange={(v) => setSeriesDefaultVis(v)} />
          <p className="form-help">새 시리즈 생성 시 기본으로 적용될 공개 범위입니다.</p>
        </div>
        <div className="form-group">
          <label>에피소드 홍보글 기본 공개 설정</label>
          <VisibilitySelector value={episodeDefaultVis} onChange={(v) => setEpisodeDefaultVis(v)} />
          <p className="form-help">새 에피소드 홍보글에 기본으로 적용될 공개 범위입니다.</p>
        </div>
        <div className="form-group">
          <label>
            <input type="checkbox" checked={isLocked} onChange={(e) => setIsLocked(e.target.checked)} />
            {" "}<Icon name="lock" /> 팔로워 수동 승인
          </label>
          <p className="form-help">켜면 다른 사용자가 팔로우할 때 수동으로 승인해야 팔로워가 됩니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">설정 저장</button>
        </div>
      </form>

      <hr style={{ margin: "32px 0", border: "none", borderTop: "1px solid var(--border)" }} />

      <div className="page-header">
        <h2>커스텀 이모지</h2>
      </div>

      <form onSubmit={async (e) => {
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
            setEmojiKeyword("");
            setEmojiCategory("");
            setEmojiAliases("");
            setEmojiFile(null);
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
          <input type="text" value={emojiKeyword} onChange={(e) => setEmojiKeyword(e.target.value.replace(/[^a-z0-9_]/gi, "_").toLowerCase())} placeholder="blobcat" required className="cw-input" style={{ width: "100%" }} />
        </div>
        <div className="form-group">
          <label>카테고리</label>
          <input type="text" value={emojiCategory} onChange={(e) => setEmojiCategory(e.target.value)} placeholder="기본" className="cw-input" style={{ width: "100%" }} />
        </div>
        <div className="form-group">
          <label>별칭 <small>(쉼표로 구분)</small></label>
          <input type="text" value={emojiAliases} onChange={(e) => setEmojiAliases(e.target.value)} placeholder="blob, blob_cat" className="cw-input" style={{ width: "100%" }} />
        </div>
        <div className="form-group">
          <label>이미지 <small>(PNG, JPEG, WebP, GIF - 33x33으로 리사이징)</small></label>
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(e) => setEmojiFile(e.target.files?.[0] || null)} required style={{ display: "block", marginTop: 4 }} />
        </div>
        <div className="form-actions">
          <button type="submit" disabled={emojiSubmitting || !emojiFile || !emojiKeyword.trim()} className="btn btn-primary">업로드</button>
        </div>
      </form>

      <div style={{ marginTop: 24 }}>
        {emojis.length === 0 ? (
          <p className="empty-state">등록된 커스텀 이모지가 없습니다.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {emojis.map((emo) => (
              <div key={emo.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10 }}>
                <img src={emo.url} alt={emo.keyword} width={33} height={33} style={{ width: 33, height: 33, borderRadius: 4, objectFit: "contain", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>:<span style={{ color: "var(--accent)" }}>{emo.keyword}</span>:</div>
                  <div style={{ fontSize: "0.85em", color: "var(--text-muted)" }}>
                    {emo.category && <span>#{emo.category}</span>}
                    {emo.aliases && emo.aliases.length > 0 && <span> {emo.aliases.map(a => `:${a}:`).join(" ")}</span>}
                  </div>
                </div>
                <button type="button" onClick={async () => {
                  if (!confirm(`:${emo.keyword}:를 삭제하시겠습니까?`)) return;
                  try {
                    const res = await fetch(`/api/emojis/${emo.id}`, { method: "DELETE", credentials: "include" });
                    if (res.ok) {
                      setEmojis(emojis.filter(e => e.id !== emo.id));
                      invalidateEmojiCache();
                    }
                  } catch {}
                }} className="btn" style={{ color: "var(--danger)", border: "1px solid var(--border)", padding: "4px 12px", fontSize: "0.85em" }}>삭제</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
