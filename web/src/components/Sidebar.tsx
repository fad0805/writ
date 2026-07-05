"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import Icon from "./Icon";
import { avatarColor } from "@/lib/avatar";

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
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, [user]);
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
    await api.logout();
    await refresh();
    router.push("/login");
  };

  const isActive = (href: string) => {
    if (!pathname) return false;
    if (href === "/timeline/home") return pathname.startsWith("/timeline");
    if (href === "/novels/my") return pathname === "/novels/my";
    if (href === "/novels") return pathname === "/novels";
    if (user && href === `/profile/${user.username}`) return pathname === `/profile/${user.username}`;
    return pathname === href || pathname.startsWith(href + "/") || pathname.startsWith(href + "?");
  };

  if (!mounted || loading) {
    return (
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link href="/timeline/home" className="sidebar-home-link"><h2><span style={{ display: "inline-block", width: 28, height: 28, backgroundColor: "var(--accent)", mask: "url(/logo.svg) center/contain no-repeat", WebkitMask: "url(/logo.svg) center/contain no-repeat", verticalAlign: "middle" }} />WRIT</h2></Link>
        </div>
      </aside>
    );
  }

  if (!user) {
    return (
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link href="/timeline/home" className="sidebar-home-link"><h2><span style={{ display: "inline-block", width: 28, height: 28, backgroundColor: "var(--accent)", mask: "url(/logo.svg) center/contain no-repeat", WebkitMask: "url(/logo.svg) center/contain no-repeat", verticalAlign: "middle" }} />WRIT</h2></Link>
        </div>
        <ul className="nav-links">
          <NavItem href="/explore" active={isActive("/explore")}>
            <Icon name="search" /> 탐색
          </NavItem>
          <li className="nav-divider" />
          <NavItem href="/novels" active={isActive("/novels")}>
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
        <Link href="/timeline/home" className="sidebar-home-link">
          <h2><span style={{ display: "inline-block", width: 28, height: 28, backgroundColor: "var(--accent)", mask: "url(/logo.svg) center/contain no-repeat", WebkitMask: "url(/logo.svg) center/contain no-repeat", verticalAlign: "middle" }} />WRIT</h2>
        </Link>
      </div>
      <form className="sidebar-search" onSubmit={async (e) => {
        e.preventDefault();
        const q = (e.target as HTMLFormElement).q.value.trim();
        if (!q) return;
        if (q.startsWith("http")) {
          try {
            const form = new FormData();
            form.append("url", q);
            const res = await fetch("/api/fetch-post", { method: "POST", credentials: "include", body: form });
          if (res.ok) router.push("/timeline/home");
          else { const text = await res.text().catch(() => ""); alert("불러오기 실패: " + text.slice(0, 100)); }
        } catch (e: any) { alert("불러오기 실패: " + (e.message || "")); }
        }
      }} style={{ position: "relative" }}>
        <span style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", zIndex: 1, color: "var(--text-muted)", display: "flex", alignItems: "center", cursor: "pointer" }} onClick={(ev) => { const f = (ev.target as HTMLElement).closest('form'); if (f) f.requestSubmit(); }}>
          <Icon name="search" size={14} />
        </span>
        <input type="text" name="q" placeholder="검색..." className="sidebar-search-input" style={{ paddingLeft: 30 }} />
      </form>
      <Link href={`/profile/${user.username}`} className="user-info-link">
        <div className="user-info">
          <div className="sidebar-avatar rounded-[8px] flex items-center justify-center text-white font-bold text-lg" style={{ backgroundColor: avatarColor(user.username) }}>
            {(user.display_name || user.username)[0]}
          </div>
          <div className="user-info-text-mini">
            <strong>{user.display_name}</strong>
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
        <NavItem href="/novels/my" active={isActive("/novels/my")}>
          <Icon name="book_solid" /> 내 시리즈
        </NavItem>
        <NavItem href="/novels" active={isActive("/novels")}>
          <Icon name="books_solid" /> 모든 시리즈
        </NavItem>
        <li className="nav-divider" />
        <NavItem href={`/profile/${user.username}`} active={isActive(`/profile/${user.username}`)}>
          <Icon name="user_solid" /> 내 프로필
        </NavItem>
        <li className="nav-divider" />
        <NavItem href="/users/settings" active={isActive("/users/settings")}>
          <Icon name="settings" /> 설정 관리
        </NavItem>
        {user.is_admin && (
          <NavItem href="/admin" active={isActive("/admin")}>
            <Icon name="settings" /> 관리
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
