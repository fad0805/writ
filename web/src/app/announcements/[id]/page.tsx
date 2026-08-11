"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";
import Link from "next/link";
import { Announcement, fmtAnnouncementTime } from "@/lib/announcements";

export default function AnnouncementDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [item, setItem] = useState<Announcement | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPollResults, setShowPollResults] = useState(false);
  const [voting, setVoting] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (!id || !user) return;
    fetch(`/api/announcements/${id}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        setItem(d);
        if (d) {
          fetch(`/api/announcements/${id}/read`, { method: "POST", credentials: "include" }).catch(() => {});
          window.dispatchEvent(new Event("announcementchange"));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, user]);

  const handleVote = async (option: number) => {
    if (!item || voting) return;
    setVoting(true);
    try {
      const fd = new FormData();
      fd.append("option", String(option));
      const res = await fetch(`/api/announcements/${id}/vote`, { method: "POST", credentials: "include", body: fd });
      if (res.ok) {
        const d = await res.json();
        if (d.announcement) setItem(d.announcement);
      }
    } catch {}
    setVoting(false);
  };

  const handleUnvote = async () => {
    if (!item || voting) return;
    setVoting(true);
    try {
      const res = await fetch(`/api/announcements/${id}/unvote`, { method: "POST", credentials: "include" });
      if (res.ok) {
        const d = await res.json();
        if (d.announcement) setItem(d.announcement);
      }
    } catch {}
    setVoting(false);
  };

  if (authLoading || loading) return <p className="empty-state">로딩 중...</p>;
  if (!user) return null;
  if (!item) return <p className="empty-state">공지사항을 찾을 수 없습니다.</p>;

  const poll = item.poll_data;
  const myVote = item.my_vote;
  const isActive = item.active !== false;
  const totalVotes = poll ? poll.options.reduce((s, o) => s + (o.votes_count || 0), 0) : 0;
  const showResults = poll ? (showPollResults || myVote != null || !isActive) : false;
  const canVote = poll ? (!showPollResults && myVote == null && isActive) : false;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <Link href="/announcements" style={{ fontSize: 13, color: "var(--accent)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 16 }}>
        <Icon name="chevron_left" size={14} /> 공지사항 목록
      </Link>
      <h1 style={{ fontSize: 22, marginBottom: 8 }}><Icon name="star_filled" /> {item.title}</h1>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>
        {item.created_by ? `${item.created_by} · ` : ""}{fmtAnnouncementTime(item.created_at)}
        {(item.starts_at || item.ends_at) && (
          <span> · 노출 기간: {fmtAnnouncementTime(item.starts_at) || "무기한"} ~ {fmtAnnouncementTime(item.ends_at) || "무기한"}</span>
        )}
      </div>
      <div style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, padding: "20px 24px", fontSize: 15, lineHeight: 1.7, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
        {item.content || "내용이 없습니다."}
      </div>
      {poll && poll.options.length > 0 && (
        <div style={{ marginTop: 16, padding: 12, borderRadius: 10, background: "var(--bg-tertiary)", border: "1px solid var(--border)" }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>
            <Icon name="chart" size={14} /> 투표
          </div>
          {poll.options.map((opt, i) => {
            const pct = showResults && totalVotes > 0 ? Math.round(((opt.votes_count || 0) / totalVotes) * 100) : 0;
            const isSelected = myVote === i;
            return (
              <div
                key={i}
                role="button"
                tabIndex={canVote ? 0 : undefined}
                onClick={(e) => { e.preventDefault(); if (canVote) handleVote(i); }}
                onKeyDown={(e) => { if (canVote && e.key === "Enter") handleVote(i); }}
                style={{
                  position: "relative", padding: "9px 12px", marginBottom: 6, borderRadius: 8,
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                  background: isSelected ? "color-mix(in srgb, var(--accent) 15%, transparent)" : "var(--bg-secondary)",
                  cursor: canVote ? "pointer" : "default", overflow: "hidden", transition: "all 0.15s",
                }}
              >
                {showResults && <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${pct}%`, background: "color-mix(in srgb, var(--accent) 12%, transparent)", borderRadius: 8, transition: "width 0.3s" }} />}
                <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <span style={{ fontWeight: isSelected ? 600 : 400, fontSize: 14 }}>{opt.text}</span>
                  {showResults && <span style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 40, textAlign: "right", flexShrink: 0 }}>{pct}%</span>}
                </div>
              </div>
            );
          })}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
            <span>총 {totalVotes}표</span>
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {canVote && (
                <button type="button" className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }} onClick={() => setShowPollResults(true)}>결과 보기</button>
              )}
              {myVote == null && showPollResults && isActive && (
                <button type="button" className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }} onClick={() => setShowPollResults(false)}>투표하기</button>
              )}
              {myVote != null && isActive && (
                <button type="button" className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }} onClick={handleUnvote}>투표 취소</button>
              )}
              {voting && <span>처리 중...</span>}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
