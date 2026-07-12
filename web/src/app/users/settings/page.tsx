"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, User } from "@/lib/api";
import Icon from "@/components/Icon";
import Avatar from "@/components/Avatar";
import VisibilitySelector from "@/components/VisibilitySelector";
import SettingsNav from "@/components/SettingsNav";
import { useAuth } from "@/lib/auth";
import { isPushSupported, getPermissionState, subscribePush, unsubscribePush, isSubscribed } from "@/lib/push";

export default function SettingsPage() {
  const router = useRouter();
  const { refresh: refreshAuth } = useAuth();
  const [defaultVis, setDefaultVis] = useState("public");
  const [showBadge, setShowBadge] = useState(false);
  const [isLocked, setIsLocked] = useState(false);
  const [isBot, setIsBot] = useState(false);
  const [followListVis, setFollowListVis] = useState("public");
  const [enableReactions, setEnableReactions] = useState(true);
  const [followRequests, setFollowRequests] = useState<{ id: number; user: User }[]>([]);
  const [frLoading, setFrLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pushSupported, setPushSupported] = useState(false);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushLoading, setPushLoading] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    api.me().then((u) => {
      const user = u as any;
      setDefaultVis(user.default_visibility || "public");
      setShowBadge(user.show_badge || false);
      setIsLocked(user.is_locked || false);
      setIsBot(user.is_bot || false);
      setFollowListVis(user.follow_list_visibility || "public");
      setEnableReactions(user.enable_reactions !== false);
      setLoading(false);
    }).catch(() => router.push("/login"));
  }, [router]);

  useEffect(() => {
    fetch("/api/follow-requests", { credentials: "include" })
      .then(r => r.json()).then(d => { setFollowRequests(d.requests || []); setFrLoading(false); })
      .catch(() => setFrLoading(false));
  }, []);

  useEffect(() => {
    isPushSupported().then((supported) => {
      setPushSupported(supported);
      if (supported) isSubscribed().then(setPushEnabled);
    });
  }, []);

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

  const handlePushToggle = async () => {
    if (pushLoading) return;
    setPushLoading(true);
    try {
      if (pushEnabled) {
        await unsubscribePush();
        setPushEnabled(false);
      } else {
        const ok = await subscribePush();
        setPushEnabled(ok);
      }
    } catch (e: any) {
      console.error("Push toggle error:", e);
      alert(`알림 설정 중 오류가 발생했습니다: ${e.message || e}`);
    }
    setPushLoading(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("default_visibility", defaultVis);
      form.append("show_badge", showBadge ? "true" : "");
      form.append("is_locked", isLocked ? "true" : "");
      form.append("is_bot", isBot ? "true" : "");
      form.append("follow_list_visibility", followListVis);
      form.append("enable_reactions", enableReactions ? "true" : "false");
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
          <label>포스트 기본 공개 설정</label>
          <VisibilitySelector value={defaultVis} onChange={(v) => setDefaultVis(v)} />
          <p className="form-help">새 포스트에 기본으로 적용될 공개 범위입니다.</p>
        </div>

        <div className="form-group">
          <label>
            <input type="checkbox" checked={isLocked} onChange={(e) => setIsLocked(e.target.checked)} />
            {" "}<Icon name="lock" /> 팔로우 수동 승인
          </label>
          <p className="form-help">켜면 다른 사용자가 회원님을 팔로우할 때 수락이 필요합니다. 아래 팔로우 요청에서 관리할 수 있습니다.</p>
        </div>
        <div className="form-group">
          <label>
            <input type="checkbox" checked={isBot} onChange={(e) => setIsBot(e.target.checked)} />
            {" "}<Icon name="mute" /> 자동화된 계정 (봇)
          </label>
          <p className="form-help">봇 계정은 사용자가 거의 개입하지 않고 프로그램으로 자동 운영되는 계정입니다. 켜면 계정에 봇 표시가 추가됩니다.</p>
        </div>
        <div className="form-group">
          <label>
            <input type="checkbox" checked={enableReactions} onChange={(e) => setEnableReactions(e.target.checked)} />
            {" "}리액션(이모지 반응) 허용
          </label>
          <p className="form-help">켜면 다른 사용자가 내 포스트에 이모지로 반응할 수 있습니다.</p>
        </div>
        <div className="form-group">
          <label>팔로워/팔로잉 목록 공개</label>
          <div className="visibility-selector">
            <label><input type="radio" name="follow_list_vis" value="public" checked={followListVis === "public"} onChange={() => setFollowListVis("public")} /><Icon name="globe" /> 공개</label>
            <label><input type="radio" name="follow_list_vis" value="private" checked={followListVis === "private"} onChange={() => setFollowListVis("private")} /><Icon name="lock" /> 비공개</label>
          </div>
          <p className="form-help">비공개로 설정하면 다른 사용자가 회원님의 팔로워/팔로잉 목록을 볼 수 없으며 숫자가 0으로 표시됩니다.</p>
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
        {pushSupported && (
          <div className="form-group">
            <label>
              <input type="checkbox" checked={pushEnabled} disabled={pushLoading} onChange={handlePushToggle} />
              {" "}<Icon name="bell" /> 브라우저 알림 {pushEnabled ? "활성화됨" : "비활성화됨"}
            </label>
            <p className="form-help">브라우저가 꺼져 있어도 새로운 알림을 받을 수 있습니다.</p>
          </div>
        )}
        <div className="form-actions">
          <button type="submit" disabled={submitting} className="btn btn-primary">설정 저장</button>
        </div>
      </form>

      <div className="novel-form" style={{ marginTop: 20 }}>
        <h3 style={{ fontSize: "1.1em", marginBottom: 16 }}><Icon name="user_solid" /> 팔로우 요청</h3>
        {frLoading ? (
          <p className="empty-small">로딩 중...</p>
        ) : followRequests.length === 0 ? (
          <p className="empty-small">팔로우 요청이 없습니다.</p>
        ) : followRequests.map((fr) => (
          <div key={fr.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: "var(--bg-tertiary)", borderRadius: 8, marginBottom: 6 }}>
            <Avatar user={fr.user} className="sidebar-avatar" style={{ width: 32, height: 32, minWidth: 32 }} />
            <div style={{ flex: 1 }}>
              <strong style={{ fontSize: "0.9em" }}>{fr.user.display_name}</strong>
              <span style={{ fontSize: "0.8em", color: "var(--text-muted)", marginLeft: 4 }}>@{fr.user.display_handle || fr.user.username}</span>
            </div>
            <button onClick={async () => {
              await fetch(`/api/users/${encodeURIComponent(fr.user.username)}/approve-follow`, { method: "POST", credentials: "include" });
              setFollowRequests(prev => prev.filter(x => x.id !== fr.id));
            }} className="btn btn-primary btn-small">수락</button>
            <button onClick={async () => {
              await fetch(`/api/users/${encodeURIComponent(fr.user.username)}/reject-follow`, { method: "POST", credentials: "include" });
              setFollowRequests(prev => prev.filter(x => x.id !== fr.id));
            }} className="btn btn-small btn-outline">거절</button>
          </div>
        ))}
      </div>
    </>
  );
}
