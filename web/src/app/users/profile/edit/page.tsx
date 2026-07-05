"use client";
import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, User } from "@/lib/api";
import Icon from "@/components/Icon";
import { avatarColor } from "@/lib/avatar";
import TextareaHighlight from "@/components/TextareaHighlight";
import ImageCropper from "@/components/ImageCropper";
import { useAuth } from "@/lib/auth";

export default function ProfileEditPage() {
  const router = useRouter();
  const { refresh: refreshAuth } = useAuth();
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [summary, setSummary] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [avatarUrl, setAvatarUrl] = useState("");
  const [cropSrc, setCropSrc] = useState("");
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
    api.me().then((u) => {
      setUser(u);
      setDisplayName(u.display_name);
      setSummary(u.summary);
      setAvatarUrl(u.avatar || "");
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
          setImageFile(null);
          setCropSrc("");
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
    setCropSrc(makeBlob(file));
  };

  const handleCrop = (blob: Blob) => {
    revokeBlobs();
    const croppedFile = new File([blob], imageFile?.name || "avatar.jpg", { type: "image/jpeg" });
    setImageFile(croppedFile);
    setAvatarUrl(makeBlob(blob));
    setCropSrc("");
  };

  const handleCropClose = () => {
    revokeBlobs();
    setCropSrc("");
    setImageFile(null);
    setAvatarUrl(user?.avatar || "");
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
      if (imageFile) form.append("image", imageFile);
      const res = await fetch("/api/profile/update", { method: "POST", credentials: "include", body: form });
      if (res.ok) { await refreshAuth(); router.push(`/@${user?.username}`); }
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
                <input type="file" accept="image/*" onChange={handleFileChange} style={{ display: "none" }} />
              </label>
              {imageFile && <span className="profile-edit-file-name">{imageFile.name}</span>}
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
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => { revokeBlobs(); setImageFile(null); setAvatarUrl(user?.avatar || ""); router.back(); }} className="btn btn-outline">취소</button>
        </div>
      </form>
      {cropSrc && <ImageCropper src={cropSrc} onCrop={handleCrop} onClose={handleCropClose} />}
    </>
  );
}
