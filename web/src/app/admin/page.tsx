"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";

export default function AdminDashboard() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [stats, setStats] = useState({ users: 0, posts: 0, series: 0 });

  useEffect(() => {
    if (!authLoading && user?.role !== "admin" && user?.role !== "moderator") {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    fetch("/api/admin/stats", { credentials: "include" })
      .then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || (user.role !== "admin" && user.role !== "moderator")) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>

      <div className="admin-tabs">
        <Link href="/admin" className="btn btn-primary btn-small">대시보드</Link>
        <Link href="/admin/users" className="btn btn-outline btn-small">유저 관리</Link>
        <Link href="/admin/emojis" className="btn btn-outline btn-small">커스텀 이모지</Link>
      </div>

      <div className="grid-3">
        <div className="stat-card">
          <Icon name="user" size={28} />
          <div className="stat-number">{stats.users}</div>
          <div className="stat-label">사용자</div>
        </div>
        <div className="stat-card">
          <Icon name="globe" size={28} />
          <div className="stat-number">{stats.posts}</div>
          <div className="stat-label">게시글</div>
        </div>
        <div className="stat-card">
          <Icon name="book" size={28} />
          <div className="stat-number">{stats.series}</div>
          <div className="stat-label">시리즈</div>
        </div>
      </div>
    </>
  );
}
