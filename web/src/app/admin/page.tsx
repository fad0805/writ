"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/permissions";
import Icon from "@/components/Icon";
import AdminNav from "@/components/AdminNav";

export default function AdminDashboard() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [stats, setStats] = useState({ users: 0, posts: 0, series: 0 });

  useEffect(() => {
    if (!authLoading && !isStaff(user)) {
      router.push("/timeline/home");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    fetch("/api/admin/stats", { credentials: "include" })
      .then(r => r.json()).then(setStats).catch(() => {});
  }, []);

  if (authLoading) return <div className="empty-state">로딩 중...</div>;
  if (!user || !isStaff(user)) return null;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 서버 관리</h2>
      </div>

      <AdminNav current="dashboard" user={user} />

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
