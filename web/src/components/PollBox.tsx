"use client";
import { useState } from "react";
import { PostData, api } from "@/lib/api";
import { formatRelative } from "@/lib/postContent";
import { useNow } from "@/hooks/useNow";
import Icon from "./Icon";

export default function PollBox({ post, targetId, readonly, onUpdate }: {
  post: PostData;
  targetId: number;
  readonly?: boolean;
  onUpdate?: (updated?: PostData) => void;
}) {
  const now = useNow(1000);
  const [showPollResults, setShowPollResults] = useState(false);
  const [pollRefreshing, setPollRefreshing] = useState(false);
  const [pollData, setPollData] = useState(post.poll_data);
  const [prevPollData, setPrevPollData] = useState(post.poll_data);
  if (post.poll_data !== prevPollData) {
    setPrevPollData(post.poll_data);
    setPollData(post.poll_data);
  }

  const total = pollData!.options.reduce((s, o) => s + (o.votes_count || 0), 0);
  const isExpired = pollData!.expires_at && new Date(pollData!.expires_at).getTime() < now;
  const showResults = showPollResults || post.my_vote != null || isExpired || readonly || post.is_mine;

  return (
    <div className="poll-box" style={{ marginTop: 8, padding: 10, borderRadius: 8, background: "var(--bg-tertiary)" }}>
      {pollData!.options.map((opt, i) => {
        const pct = showResults && total > 0 ? Math.round(((opt.votes_count || 0) / total) * 100) : 0;
        const isSelected = post.my_vote === i;
        const canVote = !showResults && !isExpired && post.my_vote == null && !readonly && !post.is_mine;
        return (
          <div
            key={i}
            className={`poll-option${isSelected ? " selected" : ""}${canVote ? " votable" : ""}`}
            onClick={async (e) => {
              e.stopPropagation();
              if (!canVote) return;
              try {
                const result = await api.vote(targetId, i);
                if (result?.post?.poll_data) {
                  setPollData(result.post.poll_data);
                }
                if (onUpdate) onUpdate();
                else window.dispatchEvent(new Event("postchange"));
                } catch (err) { alert(err instanceof Error ? err.message : String(err)); }
            }}
            style={{
              position: "relative", padding: "8px 10px", marginBottom: 4, borderRadius: 6,
              border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
              background: isSelected ? "color-mix(in srgb, var(--accent) 15%, transparent)" : "var(--bg-secondary)",
              cursor: canVote ? "pointer" : "default", overflow: "hidden",
              transition: "all 0.15s",
            }}
          >
            {showResults && <div style={{ position: "absolute", top: 0, left: 0, height: "100%", width: `${pct}%`, background: "color-mix(in srgb, var(--accent) 12%, transparent)", borderRadius: 6, transition: "width 0.3s" }} />}
            <div style={{ position: "relative", zIndex: 1, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: isSelected ? 600 : 400, fontSize: 14 }}>{opt.text}</span>
              {showResults && <span style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 40, textAlign: "right" }}>{pct}%</span>}
            </div>
          </div>
        );
      })}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            총 {typeof total === "number" ? total : 0}표
          {!post.is_mine && post.ap_id && (
            <button
              type="button"
              onClick={async (e) => {
                e.stopPropagation();
                if (pollRefreshing) return;
                setPollRefreshing(true);
                try {
                  const result = await api.refreshPoll(targetId);
                  if (result?.post?.poll_data) setPollData(result.post.poll_data);
                  if (onUpdate) onUpdate();
                  else window.dispatchEvent(new Event("postchange"));
              } catch (err) { alert(err instanceof Error ? err.message : String(err)); }
                finally { setPollRefreshing(false); }
              }}
              className="action-btn"
              style={{ fontSize: 10, padding: "1px 4px", lineHeight: 1 }}
              title="원격 서버에서 최신 투표 결과 가져오기"
            >
              <span style={pollRefreshing ? { animation: "spin 1s linear infinite" } : undefined}><Icon name="refresh" /></span>
            </button>
          )}
        </span>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {!showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
            <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(true); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>결과 보기</button>
          )}
          {showResults && post.my_vote == null && !isExpired && !readonly && !post.is_mine && (
            <button type="button" onClick={(e) => { e.stopPropagation(); setShowPollResults(false); }} className="action-btn" style={{ fontSize: 11, padding: "2px 6px" }}>투표하기</button>
          )}
          {pollData!.expires_at ? (
            new Date(pollData!.expires_at).getTime() < now ? <span>종료</span> : <span>{formatRelative(pollData!.expires_at, now)}</span>
          ) : null}
        </span>
      </div>
    </div>
  );
}
