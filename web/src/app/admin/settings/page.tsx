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
        setLogo(d.logo || "");
        setFavicon(d.favicon || "");
        setAppIcon(d.app_icon || "");
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
      form.append("logo", logo);
      form.append("favicon", favicon);
      form.append("app_icon", appIcon);
      form.append("admin_ids", adminIds);
      form.append("admin_email", adminEmail);
      const res = await fetch("/api/admin/settings", { method: "POST", credentials: "include", body: form });
      if (res.ok) { setMsg("저장되었습니다."); window.dispatchEvent(new Event("serverchange")); }
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
          <input type="text" value={serverName} onChange={(e) => setServerName(e.target.value.slice(0, 20))} className="cw-input" placeholder="WRIT" maxLength={20} />
          <p className="form-help">최대 20자까지 입력 가능합니다.</p>
        </div>
        <div className="form-group">
          <label>대표 아이콘 (URL)</label>
          <input type="text" value={logo} onChange={(e) => setLogo(e.target.value)} className="cw-input" placeholder="https://example.com/logo.png" />
          <p className="form-help">정사각형 이미지를 사용해 주세요.</p>
          {logo && <img src={logo} alt="logo" style={{ width: 80, height: 80, marginTop: 8, borderRadius: 12, objectFit: "cover" }} />}
        </div>
        <div className="form-group">
          <label>파비콘 (URL)</label>
          <input type="text" value={favicon} onChange={(e) => setFavicon(e.target.value)} className="cw-input" placeholder="https://example.com/favicon.ico" />
          <p className="form-help">정사각형 이미지를 사용해 주세요. .ico 확장자만 지원됩니다.</p>
        </div>
        <div className="form-group">
          <label>모바일 앱 아이콘 (URL)</label>
          <input type="text" value={appIcon} onChange={(e) => setAppIcon(e.target.value)} className="cw-input" placeholder="https://example.com/app-icon.png" />
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
