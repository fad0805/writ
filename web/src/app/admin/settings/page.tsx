"use client";
import { useState, useEffect, useRef } from "react";
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
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [faviconFile, setFaviconFile] = useState<File | null>(null);
  const [appIconFile, setAppIconFile] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState("");
  const [faviconPreview, setFaviconPreview] = useState("");
  const [appIconPreview, setAppIconPreview] = useState("");
  const [adminIds, setAdminIds] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
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
        setLogo(d.logo || ""); setLogoPreview(d.logo || "");
        setFavicon(d.favicon || ""); setFaviconPreview(d.favicon || "");
        setAppIcon(d.app_icon || ""); setAppIconPreview(d.app_icon || "");
        setAdminIds(d.admin_ids || "");
        setAdminEmail(d.admin_email || "");
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
      if (logoFile) form.append("logo", logoFile);
      else form.append("logo_url", logo);
      if (faviconFile) form.append("favicon", faviconFile);
      else form.append("favicon_url", favicon);
      if (appIconFile) form.append("app_icon", appIconFile);
      else form.append("app_icon_url", appIcon);
      form.append("admin_ids", adminIds);
      form.append("admin_email", adminEmail);
      const res = await fetch("/api/admin/settings", { method: "POST", credentials: "include", body: form });
      if (res.ok) { setMsg("저장되었습니다."); window.dispatchEvent(new Event("serverchange")); }
      else { const d = await res.json().catch(() => ({})); setMsg(d.detail || "저장 실패"); }
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
          <input type="text" value={serverName} onChange={(e) => setServerName(e.target.value.slice(0, 20))} className="cw-input" placeholder="WRIT" maxLength={20} />
          <p className="form-help">최대 20자까지 입력 가능합니다.</p>
        </div>
        <div className="form-group">
          <label>대표 아이콘</label>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {logoPreview && <img src={logoPreview} alt="logo" style={{ width: 64, height: 64, borderRadius: 12, objectFit: "cover", flexShrink: 0 }} />}
            <input type="file" accept="image/*" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setLogoFile(f); setLogoPreview(URL.createObjectURL(f)); } }} className="cw-input" />
          </div>
          <p className="form-help">정사각형 이미지를 사용해 주세요.</p>
        </div>
        <div className="form-group">
          <label>파비콘</label>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {faviconPreview && <img src={faviconPreview} alt="favicon" style={{ width: 32, height: 32, borderRadius: 4, objectFit: "cover", flexShrink: 0 }} />}
            <input type="file" accept="image/x-icon,image/png,image/svg+xml" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFaviconFile(f); setFaviconPreview(URL.createObjectURL(f)); } }} className="cw-input" />
          </div>
          <p className="form-help">정사각형 이미지를 사용해 주세요.</p>
        </div>
        <div className="form-group">
          <label>모바일 앱 아이콘</label>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {appIconPreview && <img src={appIconPreview} alt="app icon" style={{ width: 64, height: 64, borderRadius: 12, objectFit: "cover", flexShrink: 0 }} />}
            <input type="file" accept="image/*" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setAppIconFile(f); setAppIconPreview(URL.createObjectURL(f)); } }} className="cw-input" />
          </div>
          <p className="form-help">정사각형 이미지를 사용해 주세요.</p>
        </div>
        <div className="form-group">
          <label>관리자 계정</label>
          <input type="text" value={adminIds} onChange={(e) => setAdminIds(e.target.value)} className="cw-input" placeholder="owner" />
          <p className="form-help">서버 정보에 표시할 관리자 계정 핸들을 입력하세요. 기본값은 owner입니다.</p>
        </div>
        <div className="form-group">
          <label>관리 이메일</label>
          <input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} className="cw-input" placeholder="admin@example.com" />
          <p className="form-help">서버 정보에 표시할 관리 이메일 주소입니다. 비워두면 설정된 관리자 계정의 이메일이 표시됩니다.</p>
        </div>
        <div className="form-actions">
          <button type="submit" disabled={saving} className="btn btn-primary">{saving ? "저장 중..." : "저장"}</button>
        </div>
      </form>
    </>
  );
}
