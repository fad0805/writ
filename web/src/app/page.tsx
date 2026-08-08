"use client";
import { useAuth } from "@/lib/auth";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Icon from "@/components/Icon";
import Link from "next/link";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [serverInfo, setServerInfo] = useState<{ name: string; logo: string; description?: string } | null>(null);

  useEffect(() => {
    fetch("/api/server-info").then((r) => r.json()).then(setServerInfo).catch(() => {});
  }, []);

  useEffect(() => {
    if (!loading && user) router.replace("/timeline/home");
  }, [user, loading, router]);

  if (loading) return <div className="empty-state">{serverInfo?.logo ? <img src={serverInfo.logo} alt="" style={{ width: 48, height: 48, marginBottom: 12, objectFit: "contain" }} /> : null}<br />로딩 중...</div>;
  if (user) return null;

  return (
    <div className="home-container">
      <div className="home-logo">{serverInfo?.logo ? <img src={serverInfo.logo} alt={serverInfo?.name || "WRIT"} /> : <span className="home-logo-default" />}</div>
      <h1 className="home-title">{serverInfo?.name || "WRIT"}</h1>
      {serverInfo?.description && <p className="home-desc" style={{ marginTop: -8 }}>{serverInfo.description}</p>}
      <p className="home-desc">
        작가를 위한 소셜 네트워크입니다.<br />
        소설을 연재하고, 독자와 소통하고, 글을 나누세요.
      </p>
      <div className="home-buttons">
        <Link href="/login" className="btn btn-primary">로그인</Link>
        <Link href="/register" className="btn btn-outline">가입</Link>
      </div>
      <div className="home-features">
        <div><Icon name="globe" size={24} /><br />연합 타임라인</div>
        <div><Icon name="book" size={24} /><br />시리즈 연재</div>
        <div><Icon name="mention" size={24} /><br />다이렉트 메시지</div>
        <div><Icon name="star" size={24} /><br />즐겨찾기</div>
      </div>
    </div>
  );
}
