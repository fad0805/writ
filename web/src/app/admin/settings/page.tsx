"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

export default function AdminSettingsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [serverName, setServerName] = useState("");
  const [logo, setLogo] = useState("");
  const [favicon, setFavicon] = useState("");
  const [appIcon, setAppIcon] = useState("");
  const [adminIds, setAdminIds] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator" && user?.role !== "owner") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (authLoading) return;
    fetch("/api/admin/settings", { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        setServerName(d.server_name || "");
        setLogo(d.logo || "");
        setFavicon(d.favicon || "");
        setAppIcon(d.app_icon || "");
        setAdminIds(d.admin_ids || "");
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [authLoading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const form = new FormData();
      form.append("server_name", serverName);
      form.append("logo", logo);
      form.append("favicon", favicon);
      form.append("app_icon", appIcon);
      form.append("admin_ids", adminIds);
      const res = await fetch("/api/admin/settings", { method: "POST", credentials: "include", body: form });
      if (res.ok) setMsg("저장되었습니다.");
      else setMsg("저장 실패");
    } catch { setMsg("오류 발생"); }
    setSaving(false);
  };

  if (authLoading || loading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator" && user.role !== "owner")) return null;

  return (
    <>
      <div className="page-header"><h2><Icon name="settings" /> 서버 관리</h2></div>
      <AdminNav current="settings" />
      {msg && <p style={{ marginBottom: 12, color: "var(--accent)", fontWeight: 600 }}>{msg}</p>}
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>서버 이름</label>
          <input type="text" value={serverName} onChange={(e) => setServerName(e.target.value)} className="cw-input" placeholder="WRIT" />
        </div>
        <div className="form-group">
          <label>대표 아이콘 (URL)</label>
          <input type="text" value={logo} onChange={(e) => setLogo(e.target.value)} className="cw-input" placeholder="https://example.com/logo.png" />
          {logo && <img src={logo} alt="logo" style={{ maxWidth: 80, maxHeight: 80, marginTop: 8, borderRadius: 8 }} />}
        </div>
        <div className="form-group">
          <label>파비콘 (URL)</label>
          <input type="text" value={favicon} onChange={(e) => setFavicon(e.target.value)} className="cw-input" placeholder="https://example.com/favicon.ico" />
        </div>
        <div className="form-group">
          <label>모바일 앱 아이콘 (URL)</label>
          <input type="text" value={appIcon} onChange={(e) => setAppIcon(e.target.value)} className="cw-input" placeholder="https://example.com/app-icon.png" />
        </div>
        <div className="form-group">
          <label>관리자 역할 계정</label>
          <input type="text" value={adminIds} onChange={(e) => setAdminIds(e.target.value)} className="cw-input" placeholder="@user1, @user2, ..." />
          <p className="form-help">관리자로 표시할 계정 핸들을 쉼표로 구분해 입력하세요. 관리자/오너 권한이 없어도 됩니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "저장 중..." : "저장"}</button>
        </div>
      </form>
    </>
  );
}
