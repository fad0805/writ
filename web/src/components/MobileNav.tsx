"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/permissions";
import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import Icon from "./Icon";
import AccountSwitcher from "./AccountSwitcher";
import { subscribeAnnouncementStatus, refreshAnnouncementStatus } from "@/lib/announcements";

export default function MobileNav() {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [unreadNotifs, setUnreadNotifs] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [isDark, setIsDark] = useState(false);
  const [hasAnnouncement, setHasAnnouncement] = useState(false);
  const [unreadAnnouncement, setUnreadAnnouncement] = useState(false);
  const [showAccountSwitcher, setShowAccountSwitcher] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!user) return;
    const update = () => {
      if (typeof window !== "undefined") {
        const unread = (window as unknown as { __unreadNotifs?: number }).__unreadNotifs;
        if (unread !== undefined) setUnreadNotifs(unread);
      }
    };
    update();
    const handler = () => setUnreadNotifs(0);
    window.addEventListener("notificationsread", handler);
    window.addEventListener("notifchange", update);
    return () => {
      window.removeEventListener("notificationsread", handler);
      window.removeEventListener("notifchange", update);
    };
  }, [user]);

  useEffect(() => {
    const id = setTimeout(() => setIsDark(document.body.classList.contains("dark-theme")), 0);
    const handler = () => setIsDark(document.body.classList.contains("dark-theme"));
    window.addEventListener("themechange", handler);
    return () => { clearTimeout(id); window.removeEventListener("themechange", handler); };
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
    if (!user) return;
    const unsubscribe = subscribeAnnouncementStatus((status) => {
      setHasAnnouncement(status.has_active);
      setUnreadAnnouncement(status.unread_count > 0);
    });
    const handler = () => refreshAnnouncementStatus();
    window.addEventListener("announcementchange", handler);
    return () => { unsubscribe(); window.removeEventListener("announcementchange", handler); };
  }, [user]);

  useEffect(() => {
    const id = setTimeout(() => setMenuOpen(false), 0);
    return () => clearTimeout(id);
  }, [pathname]);

  if (loading) return null;

  const isActive = (href: string) => {
    if (!pathname) return false;
    if (href === "/timeline/home") return pathname.startsWith("/timeline");
    if (href === "/series") return pathname.startsWith("/series");
    return pathname === href || pathname.startsWith(href + "/");
  };

  const toggleTheme = () => {
    (window as unknown as { __toggleTheme: () => void }).__toggleTheme();
    window.dispatchEvent(new Event("themechange"));
  };

  const openAccountSwitcher = () => {
    setMenuOpen(false);
    setShowAccountSwitcher(true);
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
        <button onClick={() => { if (pathname?.startsWith("/timeline")) { document.querySelector(".main-content")?.scrollTo({ top: 0, behavior: "smooth" }); } else { const saved = typeof localStorage !== "undefined" ? (localStorage.getItem("lastTimelineTab") || "home") : "home"; router.push(`/timeline/${saved}`); } }} className={`mobile-nav-item${pathname?.startsWith("/timeline") ? " active" : ""}`}>
          <Icon name={pathname?.startsWith("/timeline") ? "home_solid" : "home"} size={20} />
          <span>홈</span>
        </button>
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
            <button className="mobile-more-item mobile-more-logout" onClick={openAccountSwitcher}>
              로그아웃
            </button>
            <div className="mobile-more-divider" />
            <Link href={`/@${user.username}`} className="mobile-more-item">
              <Icon name="user" /> <span>내 프로필</span>
            </Link>
            {hasAnnouncement && (
              <Link href="/announcements" className="mobile-more-item">
                <Icon name="star_filled" style={{ color: unreadAnnouncement ? "#f1c40f" : undefined }} /> <span>공지사항</span>
              </Link>
            )}
            <Link href="/my" className="mobile-more-item">
              <Icon name="archive" /> <span>내 보관함</span>
            </Link>
            <Link href="/users/settings" className="mobile-more-item">
              <Icon name="settings" /> <span>설정 관리</span>
            </Link>
            {isStaff(user) && (
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
      <AccountSwitcher open={showAccountSwitcher} onClose={() => setShowAccountSwitcher(false)} />
    </>
  );
}
