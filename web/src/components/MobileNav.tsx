"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import Icon from "./Icon";

export default function MobileNav() {
  const { user, loading, refresh } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [unreadNotifs, setUnreadNotifs] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [isDark, setIsDark] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!user) return;
    const check = () => {
      fetch("/api/notifications/unread-count", { credentials: "include" })
        .then((r) => r.json())
        .then((d) => setUnreadNotifs(d.count || 0))
        .catch(() => {});
    };
    check();
    const handler = () => setUnreadNotifs(0);
    const changeHandler = () => check();
    window.addEventListener("notificationsread", handler);
    window.addEventListener("notifchange", changeHandler);
    const interval = setInterval(check, 30000);
    return () => {
      clearInterval(interval);
      window.removeEventListener("notificationsread", handler);
      window.removeEventListener("notifchange", changeHandler);
    };
  }, [user]);

  useEffect(() => {
    setIsDark(document.body.classList.contains("dark-theme"));
    const handler = () => setIsDark(document.body.classList.contains("dark-theme"));
    window.addEventListener("themechange", handler);
    return () => window.removeEventListener("themechange", handler);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  if (loading) return null;

  const isActive = (href: string) => {
    if (!pathname) return false;
    if (href === "/timeline/home") return pathname.startsWith("/timeline");
    if (href === "/series") return pathname.startsWith("/series");
    return pathname === href || pathname.startsWith(href + "/");
  };

  const toggleTheme = () => {
    (window as any).__toggleTheme();
    window.dispatchEvent(new Event("themechange"));
  };

  const handleLogout = async () => {
    const { api } = await import("@/lib/api");
    await api.logout();
    await refresh();
    setMenuOpen(false);
    router.replace("/");
  };

  if (!user) {
    return (
      <nav className="mobile-nav">
        <Link href="/explore" className={`mobile-nav-item${isActive("/explore") ? " active" : ""}`}>
          <Icon name="search" size={20} />
          <span>탐색</span>
        </Link>
        <Link href="/series" className={`mobile-nav-item${isActive("/series") ? " active" : ""}`}>
          <Icon name={isActive("/series") ? "books_solid" : "books"} size={20} />
          <span>시리즈</span>
        </Link>
        <Link href="/login" className={`mobile-nav-item${pathname === "/login" ? " active" : ""}`}>
          <Icon name="user" size={20} />
          <span>로그인</span>
        </Link>
      </nav>
    );
  }

  return (
    <>
      <nav className="mobile-nav">
        <Link href="/timeline/home" className={`mobile-nav-item${isActive("/timeline/home") ? " active" : ""}`}>
          <Icon name={isActive("/timeline/home") ? "home_solid" : "home"} size={20} />
          <span>홈</span>
        </Link>
        <Link href="/explore" className={`mobile-nav-item${isActive("/explore") ? " active" : ""}`}>
          <Icon name="search" size={20} />
          <span>탐색</span>
        </Link>
        <Link href="/notifications" className={`mobile-nav-item${isActive("/notifications") ? " active" : ""}`}>
          <span className="mobile-nav-icon-wrap">
            <Icon name={isActive("/notifications") ? "bell_solid" : "bell"} size={20} />
            {unreadNotifs > 0 && <span className="mobile-notif-dot" />}
          </span>
          <span>알림</span>
        </Link>
        <Link href="/series/my" className={`mobile-nav-item${pathname?.startsWith("/series") ? " active" : ""}`}>
          <Icon name={pathname?.startsWith("/series") ? "books_solid" : "books"} size={20} />
          <span>시리즈</span>
        </Link>
        <button className={`mobile-nav-item${menuOpen ? " active" : ""}`} onClick={() => setMenuOpen(!menuOpen)}>
          <Icon name={menuOpen ? "x" : "menu"} size={20} />
          <span>더보기</span>
        </button>
      </nav>
      {menuOpen && (
        <div className="mobile-more-overlay" onClick={() => setMenuOpen(false)}>
          <div className="mobile-more-menu" ref={menuRef} onClick={(e) => e.stopPropagation()}>
            <button className="mobile-more-item mobile-more-logout" onClick={handleLogout}>
              로그아웃
            </button>
            <div className="mobile-more-divider" />
            <Link href={`/@${user.username}`} className="mobile-more-item">
              <Icon name="user" /> <span>내 프로필</span>
            </Link>
            <Link href="/users/settings" className="mobile-more-item">
              <Icon name="settings" /> <span>설정 관리</span>
            </Link>
            {(user.role === "admin" || user.role === "moderator" || user.role === "owner") && (
              <Link href="/admin" className="mobile-more-item">
                <Icon name="shield" /> <span>서버 관리</span>
              </Link>
            )}
            <Link href="/rules" className="mobile-more-item">
              <Icon name="lock" /> <span>서버 규칙</span>
            </Link>
            <button className="mobile-more-item" onClick={toggleTheme}>
              <Icon name={isDark ? "star" : "moon"} /> <span>{isDark ? "라이트모드" : "다크모드"}</span>
            </button>
          </div>
        </div>
      )}
    </>
  );
}
