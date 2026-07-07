"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import Icon from "@/components/Icon";
import VisibilitySelector from "@/components/VisibilitySelector";
import SeriesVisibilitySelector from "@/components/SeriesVisibilitySelector";
import SettingsNav from "@/components/SettingsNav";
import { useAuth } from "@/lib/auth";

export default function SettingsPage() {
  const router = useRouter();
  const { refresh: refreshAuth } = useAuth();
  const [defaultVis, setDefaultVis] = useState("public");
  const [seriesDefaultVis, setSeriesDefaultVis] = useState("public");
  const [episodeDefaultVis, setEpisodeDefaultVis] = useState("public");
  const [showBadge, setShowBadge] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    api.me().then((u) => {
      const user = u as any;
      setDefaultVis(user.default_visibility || "public");
      setSeriesDefaultVis(user.series_default_visibility || "public");
      setEpisodeDefaultVis(user.episode_default_visibility || "public");
      setShowBadge(user.show_badge || false);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        const form = document.querySelector(".novel-form") as HTMLFormElement;
        if (form) form.requestSubmit();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("default_visibility", defaultVis);
      form.append("series_default_visibility", seriesDefaultVis);
      form.append("episode_default_visibility", episodeDefaultVis);
      form.append("show_badge", showBadge ? "true" : "");
      const res = await fetch("/api/settings/update", {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (res.ok) { await refreshAuth(); alert("저장되었습니다"); }
      else alert("저장 실패");
    } catch { alert("저장 실패"); }
    setSubmitting(false);
  };

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <>
      <div className="page-header">
        <h2><Icon name="settings" /> 설정 관리</h2>
      </div>
      <SettingsNav current="visibility" />
      <form onSubmit={handleSubmit} className="novel-form">
        <div className="form-group">
          <label>시리즈 기본 공개 설정</label>
          <SeriesVisibilitySelector value={seriesDefaultVis} onChange={(v) => setSeriesDefaultVis(v)} />
          <p className="form-help">새 시리즈 생성 시 기본으로 적용될 공개 범위입니다.</p>
        </div>
        <div className="form-group">
          <label>에피소드 홍보글 기본 공개 설정</label>
          <VisibilitySelector value={episodeDefaultVis} onChange={(v) => setEpisodeDefaultVis(v)} />
          <p className="form-help">새 에피소드 홍보글에 기본으로 적용될 공개 범위입니다.</p>
        </div>

        {(user?.role === "admin" || user?.role === "moderator" || user?.role === "owner") && (
          <div className="form-group">
            <label>
              <input type="checkbox" checked={showBadge} onChange={(e) => setShowBadge(e.target.checked)} />
              {" "}<Icon name="shield" className="icon-shield-green" /> 관리자 뱃지 공개
            </label>
            <p className="form-help">다른 사용자에게 관리자/조율자 뱃지를 보여줍니다.</p>
          </div>
        )}
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">설정 저장</button>
        </div>
      </form>
    </>
  );
}
