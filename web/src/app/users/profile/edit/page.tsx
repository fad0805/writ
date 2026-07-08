"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, User } from "@/lib/api";
import { avatarColor } from "@/lib/avatar";
import TextareaHighlight from "@/components/TextareaHighlight";
import ImageCropper from "@/components/ImageCropper";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";

export default function ProfileEditPage() {
  const router = useRouter();
  const { refresh: refreshAuth } = useAuth();
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [summary, setSummary] = useState("");
  const [customFields, setCustomFields] = useState<{ label: string; value: string }[]>([]);
  const [profileHashtags, setProfileHashtags] = useState<string[]>([]);
  const [newHashtag, setNewHashtag] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [avatarUrl, setAvatarUrl] = useState("");
  const [cropSrc, setCropSrc] = useState("");
  const [cropKind, setCropKind] = useState<"avatar" | "header">("avatar");
  const [headerFile, setHeaderFile] = useState<File | null>(null);
  const [headerPreview, setHeaderPreview] = useState("");
  const [headerCropSrc, setHeaderCropSrc] = useState("");
  const headerInputRef = useRef<HTMLInputElement>(null);
  const blobRef = useRef<string[]>([]);

  const revokeBlobs = () => {
    blobRef.current.forEach((u) => URL.revokeObjectURL(u));
    blobRef.current = [];
  };

  const makeBlob = (src: string | Blob) => {
    const url = typeof src === "string" ? src : URL.createObjectURL(src);
    if (typeof src !== "string") blobRef.current.push(url);
    return url;
  };

  useEffect(() => {
    api.me().then((u: any) => {
      setUser(u);
      setDisplayName(u.display_name);
      setSummary(u.summary);
      setAvatarUrl(u.avatar || "");
      setHeaderPreview(u.header || "");
      setCustomFields(u.custom_fields || []);
      setProfileHashtags(u.profile_hashtags || []);
      setLoading(false);
    }).catch(() => router.push("/login"));
    return revokeBlobs;
  }, [router]);

  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) {
        revokeBlobs();
        api.me().then((u) => {
          setUser(u);
          setDisplayName(u.display_name);
          setSummary(u.summary);
          setAvatarUrl(u.avatar || "");
          setHeaderPreview(u.header || "");
          setImageFile(null);
          setHeaderFile(null);
          setCropSrc("");
          setHeaderCropSrc("");
        }).catch(() => {});
      }
    };
    window.addEventListener("pageshow", onShow);
    return () => {
      window.removeEventListener("pageshow", onShow);
      revokeBlobs();
    };
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    revokeBlobs();
    setImageFile(file);
    setAvatarUrl(makeBlob(file));
    setCropKind("avatar");
    setCropSrc(makeBlob(file));
  };

  const handleHeaderFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    revokeBlobs();
    setHeaderFile(file);
    setHeaderPreview(makeBlob(file));
    setCropKind("header");
    setHeaderCropSrc(makeBlob(file));
  };

  const handleCrop = (blob: Blob) => {
    revokeBlobs();
    if (cropKind === "header") {
      const croppedFile = new File([blob], headerFile?.name || "header.jpg", { type: "image/jpeg" });
      setHeaderFile(croppedFile);
      setHeaderPreview(makeBlob(blob));
      setHeaderCropSrc("");
    } else {
      const croppedFile = new File([blob], imageFile?.name || "avatar.jpg", { type: "image/jpeg" });
      setImageFile(croppedFile);
      setAvatarUrl(makeBlob(blob));
      setCropSrc("");
    }
  };

  const handleCropClose = () => {
    revokeBlobs();
    if (cropKind === "header") {
      setHeaderCropSrc("");
      setHeaderFile(null);
      setHeaderPreview(user?.header || "");
    } else {
      setCropSrc("");
      setImageFile(null);
      setAvatarUrl(user?.avatar || "");
    }
  };

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
      form.append("display_name", displayName);
      form.append("summary", summary);
      form.append("custom_fields", JSON.stringify(customFields));
      form.append("profile_hashtags", JSON.stringify(profileHashtags));
      if (imageFile) form.append("image", imageFile);
      if (headerFile) form.append("header_image", headerFile);
      const res = await fetch("/api/profile/update", { method: "POST", credentials: "include", body: form });
      if (res.ok) { await refreshAuth(); window.dispatchEvent(new Event("profilechange")); router.push(`/@${user?.username}`); }
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;
  if (!user) return <p className="empty-state">사용자 정보를 불러올 수 없습니다.</p>;

  return (
    <>
      <h2>프로필 수정</h2>
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>프로필 이미지</label>
          <div className="profile-edit-avatar-wrap">
            {avatarUrl ? (
              <img src={avatarUrl} alt="" className="profile-edit-avatar-thumb" />
            ) : (
              <div className="profile-edit-avatar-thumb fallback" style={{ backgroundColor: avatarColor(user.username) }}>
                {(displayName || user.username)[0]}
              </div>
            )}
            <div className="profile-edit-file-row">
              <label className="btn btn-outline btn-small profile-edit-file-label">
                파일 선택
                <input type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
              </label>
              {imageFile && <span className="profile-edit-file-name">{imageFile.name}</span>}
            </div>
          </div>
        </div>
        <div className="form-group">
          <label>헤더 이미지</label>
          <div className="profile-edit-avatar-wrap">
            {headerPreview && <img src={headerPreview} alt="" className="profile-edit-header-thumb" />}
            <div>
              <div className="profile-edit-file-row">
                <label className="btn btn-outline btn-small profile-edit-file-label">
                  파일 선택
                  <input type="file" ref={headerInputRef} accept="image/*" onChange={handleHeaderFileChange} className="hidden" />
                </label>
                {headerFile && <span className="profile-edit-file-name">{headerFile.name}</span>}
              </div>
            </div>
          </div>
        </div>
        <div className="form-group">
          <label>표시 이름</label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="사용자 표시 이름" />
        </div>
        <div className="form-group">
          <label>소개글</label>
          <TextareaHighlight value={summary} onChange={(v) => setSummary(v)} placeholder="자기소개" maxLength={3000} cwLength={0} rows={3} />
          <div className="char-count">{summary.length}/{3000}</div>
        </div>
        <div className="form-group">
          <label>사용자 정의 필드</label>
          <p className="form-help">링크 등을 추가하세요. 라벨과 내용 각각 40자 제한.</p>
          {customFields.map((f, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
              <button type="button" onClick={() => { const c = [...customFields]; const tmp = c[i]; c[i] = c[i - 1]; c[i - 1] = tmp; setCustomFields(c); }} disabled={i === 0} style={{ background: "none", border: "none", cursor: i === 0 ? "default" : "pointer", color: "var(--text-muted)", padding: 0 }}>↑</button>
              <button type="button" onClick={() => { const c = [...customFields]; const tmp = c[i]; c[i] = c[i + 1]; c[i + 1] = tmp; setCustomFields(c); }} disabled={i === customFields.length - 1} style={{ background: "none", border: "none", cursor: i === customFields.length - 1 ? "default" : "pointer", color: "var(--text-muted)", padding: 0 }}>↓</button>
              <input type="text" value={f.label} onChange={e => { const c = [...customFields]; c[i] = { ...c[i], label: e.target.value.slice(0, 40) }; setCustomFields(c); }} placeholder="라벨" className="cw-input" style={{ width: 120 }} maxLength={40} />
              <input type="text" value={f.value} onChange={e => { const c = [...customFields]; c[i] = { ...c[i], value: e.target.value.slice(0, 40) }; setCustomFields(c); }} placeholder="내용" className="cw-input" style={{ flex: 1 }} maxLength={40} />
              <button type="button" onClick={() => setCustomFields(customFields.filter((_, j) => j !== i))} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--danger)", padding: 0 }}>×</button>
            </div>
          ))}
          <button type="button" onClick={() => setCustomFields([...customFields, { label: "", value: "" }])} className="btn btn-small btn-outline">+ 필드 추가</button>
        </div>
        <div className="form-group">
          <label>프로필 해시태그</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
            {profileHashtags.map((tag, i) => (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 12, fontSize: "0.85em" }}>
                #{tag}
                <span style={{ cursor: "pointer", color: "var(--text-dim)", fontSize: "1.1em", lineHeight: 1 }} onClick={() => setProfileHashtags(profileHashtags.filter((_, j) => j !== i))}>×</span>
              </span>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <input type="text" value={newHashtag} onChange={e => setNewHashtag(e.target.value)} placeholder="해시태그 입력" className="cw-input" style={{ flex: 1 }} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); const v = newHashtag.trim().replace(/^#/, ""); if (v && !profileHashtags.includes(v)) { setProfileHashtags([...profileHashtags, v]); setNewHashtag(""); } } }} />
            <button type="button" onClick={() => { const v = newHashtag.trim().replace(/^#/, ""); if (v && !profileHashtags.includes(v)) { setProfileHashtags([...profileHashtags, v]); setNewHashtag(""); } }} className="btn btn-outline btn-small">추가</button>
          </div>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => { revokeBlobs(); setImageFile(null); setHeaderFile(null); setAvatarUrl(user?.avatar || ""); setHeaderPreview(user?.header || ""); router.back(); }} className="btn btn-outline">취소</button>
        </div>
      </form>
      {cropSrc && <ImageCropper src={cropSrc} onCrop={handleCrop} onClose={handleCropClose} />}
      {headerCropSrc && <ImageCropper src={headerCropSrc} onCrop={handleCrop} onClose={handleCropClose} aspectRatio={3 / 1} />}
    </>
  );
}
