"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import Icon from "./Icon";
import Avatar from "./Avatar";

function NavItem({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <li>
      <Link href={href} className={active ? "active" : ""}>
        <span className="nav-item-inner">{children}</span>
      </Link>
    </li>
  );
}

export default function Sidebar() {
  const { user, loading, refresh } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [isDark, setIsDark] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [unreadNotifs, setUnreadNotifs] = useState(0);
  const [sidebarQ, setSidebarQ] = useState("");
  const [sidebarServerName, setSidebarServerName] = useState("WRIT");
  const [sidebarLogo, setSidebarLogo] = useState("");
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);

  useEffect(() => {
    fetch("/api/server-info")
      .then((r) => r.json())
      .then((d) => { setSidebarServerName((d.name || "WRIT").slice(0, 20)); setSidebarLogo(d.logo || ""); })
      .catch(() => {});
  }, [sidebarRefreshKey]);

  useEffect(() => { setMounted(true); }, []);
  useEffect(() => {
    if (!user) return;
    const check = () => {
      fetch("/api/notifications/unread-count", { credentials: "include" })
        .then((r) => r.json())
        .then((d) => setUnreadNotifs(d.count || 0))
        .catch(() => {});
    };
    check();
    const handler = () => { setUnreadNotifs(0); };
    const profileHandler = () => refresh();
    window.addEventListener("notificationsread", handler);
    window.addEventListener("profilechange", profileHandler);
    const serverHandler = () => setSidebarRefreshKey((k) => k + 1);
    window.addEventListener("serverchange", serverHandler);
    const interval = setInterval(check, 30000);
    return () => { clearInterval(interval); window.removeEventListener("notificationsread", handler); window.removeEventListener("profilechange", profileHandler); window.removeEventListener("serverchange", serverHandler); };
  }, [user, refresh]);
  useEffect(() => {
    setIsDark(document.body.classList.contains("dark-theme"));
    const handler = () => setIsDark(document.body.classList.contains("dark-theme"));
    window.addEventListener("themechange", handler);
    return () => window.removeEventListener("themechange", handler);
  }, []);

  const toggleTheme = () => {
    (window as any).__toggleTheme();
    window.dispatchEvent(new Event("themechange"));
  };

  const handleLogout = async () => {
    const { api } = await import("@/lib/api");
    router.replace("/");
    await api.logout();
    await refresh();
  };

  const isActive = (href: string) => {
    if (!pathname) return false;
    if (href === "/timeline/home") return pathname.startsWith("/timeline");
    if (href === "/series/my") return pathname === "/series/my";
    if (href === "/series") return pathname === "/series";
    if (user && href === `/@${user.username}`) return pathname === `/@${user.username}`;
    return pathname === href || pathname.startsWith(href + "/") || pathname.startsWith(href + "?");
  };

  if (!mounted || loading) {
    return (
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link href="/" className="sidebar-home-link"><h2>{sidebarLogo ? <img src={sidebarLogo} alt="" className="sidebar-logo-img" /> : <span className="sidebar-logo-icon" />} <span>{sidebarServerName}</span></h2></Link>
        </div>
      </aside>
    );
  }

  if (!user) {
    return (
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link href="/" className="sidebar-home-link"><h2>{sidebarLogo ? <img src={sidebarLogo} alt="" className="sidebar-logo-img" /> : <span className="sidebar-logo-icon" />} <span>{sidebarServerName}</span></h2></Link>
        </div>
        <ul className="nav-links">
          <NavItem href="/explore" active={isActive("/explore")}>
            <Icon name="search" /> 탐색
          </NavItem>
          <li className="nav-divider" />
          <NavItem href="/series" active={isActive("/series")}>
            <Icon name="books_solid" /> 모든 시리즈
          </NavItem>
        </ul>
        <div className="spacer" />
        <button className="theme-toggle" onClick={toggleTheme}>
          <Icon name={isDark ? "star" : "moon"} /> {isDark ? "라이트모드" : "다크모드"}
        </button>
        <div className="sidebar-login-btns">
          <Link href="/login" className="btn btn-primary sidebar-login-btn">로그인</Link>
          <Link href="/register" className="btn btn-outline sidebar-login-btn">가입</Link>
        </div>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Link href="/" className="sidebar-home-link">
          <h2 style={{ "--title-size": `${Math.max(0.75, 1.4 - sidebarServerName.length * 0.035)}em` } as React.CSSProperties}>{sidebarLogo ? <img src={sidebarLogo} alt="" className="sidebar-logo-img" /> : <span className="sidebar-logo-icon" />} <span>{sidebarServerName}</span></h2>
        </Link>
      </div>
      <form className="sidebar-search" onSubmit={async (e) => {
        e.preventDefault();
        const q = (e.target as HTMLFormElement).q.value.trim();
        if (!q) return;
        if (q.startsWith("http")) {
          const segments = q.replace(/\/$/, "").split("/");
          const lastSegment = segments[segments.length - 1];
          const hasPostId = /^\d+$/.test(lastSegment);
          if (q.includes("/@") && !hasPostId) {
            try {
              const form = new FormData(); form.append("url", q);
              const res = await fetch("/api/fetch-actor", { method: "POST", credentials: "include", body: form });
              if (res.ok) { const d = await res.json(); router.push(`/@${d.username}`); }
              else { alert("사용자를 찾을 수 없습니다"); }
            } catch { alert("사용자를 찾을 수 없습니다"); }
          } else {
            try {
              const form = new FormData(); form.append("url", q);
              const res = await fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form });
              if (res.ok) { const d = await res.json(); router.push(d.number ? `/@${d.author.username}/${d.number}` : `/post/${d.id}`); }
              else { alert("불러오기 실패"); }
            } catch { alert("불러오기 실패"); }
          }
        } else {
          router.push(`/explore?q=${encodeURIComponent(q)}`);
        }
      }}>
        <span className="sidebar-search-icon" onClick={(ev) => { const f = (ev.target as HTMLElement).closest('form'); if (f) f.requestSubmit(); }}>
          <Icon name="search" size={14} />
        </span>
        <input type="text" name="q" placeholder="검색..." className="sidebar-search-input padded" value={sidebarQ} onChange={e => setSidebarQ(e.target.value)} />
        {sidebarQ && (
          <span className="sidebar-search-clear" onClick={() => setSidebarQ("")}>
            <Icon name="x" size={14} />
          </span>
        )}
      </form>
      <Link href={`/@${user.username}`} className="user-info-link">
        <div className="user-info">
           <Avatar user={user} className="sidebar-avatar rounded-[8px] flex items-center justify-center text-white font-bold text-lg" />
          <div className="user-info-text-mini">
            <strong>{user.display_name} {user.is_locked && <Icon name="lock_filled" style={{ fontSize: "0.65em", verticalAlign: "middle", color: "var(--text-muted)", marginLeft: 2 }} />} {(user.role === "admin" || user.role === "moderator" || user.role === "owner") && <Icon name={user.role === "owner" ? "books_solid" : "shield_filled"} style={{ color: user.role === "owner" ? "var(--accent)" : user.role === "admin" ? "#27ae60" : "#cc8800", fontSize: "0.7em", verticalAlign: "middle", marginLeft: 3 }} title={user.role === "owner" ? "오너" : user.role === "admin" ? "관리자" : "조율자"} />}</strong>
            <span>@{user.username}</span>
          </div>
        </div>
      </Link>
      <ul className="nav-links">
        <NavItem href="/timeline/home" active={isActive("/timeline/home")}>
          <Icon name="home_solid" /> 타임라인
        </NavItem>
        <NavItem href="/notifications" active={isActive("/notifications")}>
          <Icon name="bell_solid" /> 알림
          {unreadNotifs > 0 && <span className="notif-dot" />}
        </NavItem>
        <li className="nav-divider" />
        <NavItem href="/explore" active={isActive("/explore")}>
          <Icon name="search" /> 탐색
        </NavItem>
        <li className="nav-divider" />
        <NavItem href="/series/my" active={isActive("/series/my")}>
          <Icon name="book_solid" /> 내 시리즈
        </NavItem>
        <NavItem href="/series" active={isActive("/series")}>
          <Icon name="books_solid" /> 모든 시리즈
        </NavItem>
        <li className="nav-divider" />
        <NavItem href={`/@${user.username}`} active={isActive(`/@${user.username}`)}>
          <Icon name="user_solid" /> 내 프로필
        </NavItem>
        <li className="nav-divider" />
        <NavItem href="/users/settings" active={isActive("/users/settings")}>
          <Icon name="settings_solid" /> 설정 관리
        </NavItem>
        {(user.role === "admin" || user.role === "moderator" || user.role === "owner") && (
          <NavItem href="/admin" active={isActive("/admin")}>
            <Icon name="settings" /> 서버 관리
          </NavItem>
        )}
      </ul>
      <div className="spacer" />
      <button className="theme-toggle" onClick={toggleTheme}>
        <Icon name={isDark ? "star" : "moon"} /> {isDark ? "라이트모드" : "다크모드"}
      </button>
      <button className="sidebar-btn sidebar-btn-logout" onClick={handleLogout}>
        로그아웃
      </button>
    </aside>
  );
}
