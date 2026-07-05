"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, User } from "@/lib/api";
import Icon from "@/components/Icon";
import { avatarColor } from "@/lib/avatar";

export default function ProfileEditPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [summary, setSummary] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.me().then((u) => {
      setUser(u);
      setDisplayName(u.display_name);
      setSummary(u.summary);
      setImageUrl(u.avatar);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("display_name", displayName);
      form.append("summary", summary);
      form.append("image_url", imageUrl);
      const res = await fetch("/api/profile/update", { method: "POST", credentials: "include", body: form });
      if (res.ok) router.push(`/profile/${user?.username}`);
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
          <div className="profile-avatar" style={{ backgroundColor: avatarColor(user.username), marginBottom: 10 }}>
            {(displayName || user.username)[0]}
          </div>
          <input type="text" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://example.com/avatar.jpg" />
        </div>
        <div className="form-group">
          <label>표시 이름</label>
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="사용자 표시 이름" />
        </div>
        <div className="form-group">
          <label>소개글</label>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={3} placeholder="자기소개" />
        </div>
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">저장</button>
          <button type="button" onClick={() => router.back()} className="btn btn-outline">취소</button>
        </div>
      </form>
    </>
  );
}
