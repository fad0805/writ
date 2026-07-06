"use client";
import { useAuth } from "@/lib/auth";
import { useState, useEffect } from "react";
import { api, NovelData, NotificationData } from "@/lib/api";
import Icon from "./Icon";
import Link from "next/link";
import MiniPostCard from "./MiniPostCard";

export default function RightSidebar() {
  const { user } = useAuth();
  const [novels, setNovels] = useState<NovelData[]>([]);
  const [notifs, setNotifs] = useState<NotificationData[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!user) return;
    api.getMyNovels().then((d) => setNovels(d.novels)).catch(() => {});
    api.getNotifications().then((d) => setNotifs(d.notifications.slice(0, 10))).catch(() => {});
  }, [user, refreshKey]);

  useEffect(() => {
    const handler = () => setRefreshKey((k) => k + 1);
    window.addEventListener("novelchange", handler);
    return () => window.removeEventListener("novelchange", handler);
  }, []);

  if (!user) {
    return <aside className="right-sidebar" />;
  }

  const visibleNovels = novels.slice(0, 3);
  const extraCount = novels.length - 3;
  return (
    <aside className="right-sidebar">
      <div className="widget">
        <h4><Icon name="book" /> 내 시리즈</h4>
        <div className="novel-mini-list">
          {visibleNovels.length > 0 ? visibleNovels.map((n) => (
            <Link key={n.id} href={n.number ? `/series/@${user?.username}/${n.number}` : `/series/${n.id}`} className="novel-mini-card">
              <strong>{n.title}</strong>
              <span>총 {n.episode_count}화</span>
            </Link>
          )) : (
            <p className="empty-small">연재 중인 시리즈가 없습니다.</p>
          )}
        </div>
        {extraCount > 0 && (
          <div className="more-link-wrap">
            <Link href="/series/my" className="more-link">
              더보기 +{extraCount}
            </Link>
          </div>
        )}
        <Link href="/series/new" className="btn btn-primary btn-small full-width-btn">
          + 새 시리즈 시작하기
        </Link>
      </div>
      <div className="widget">
        <h4><Icon name="bell" /> 알림</h4>
        <div className="notif-mini-list">
          {notifs.length > 0 ? notifs.map((n) => (
            n.post ? <MiniPostCard key={n.id} post={n.post} notifType={n.type} /> : null
          )) : <p className="empty-small p-0">알림이 없습니다.</p>}
        </div>
      </div>
    </aside>
  );
}
