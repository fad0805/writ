"use client";
import { useEffect, useRef, useState } from "react";
import { User, api } from "@/lib/api";
import Icon from "./Icon";
import Avatar from "./Avatar";

export default function ReactionsRow({ reactions, myReaction, onToggle, targetId, emojiMap, localEmojiMap }: {
  reactions: Record<string, number>;
  myReaction: string | null;
  onToggle: (emoji: string) => void;
  targetId: number;
  emojiMap: Record<string, string>;
  localEmojiMap: Record<string, string>;
}) {
  const [reactionTooltip, setReactionTooltip] = useState<{ emoji: string; users: User[]; x: number; y: number } | null>(null);
  const tooltipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => { if (tooltipTimerRef.current) clearTimeout(tooltipTimerRef.current); };
  }, []);

  if (!reactions || Object.keys(reactions).length === 0) return null;

  return (
    <>
      <div className="reactions-row" style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8, marginBottom: 4, padding: "0 8px" }} onClick={(e) => e.stopPropagation()}>
        {Object.entries(reactions).sort(([a], [b]) => a === "★" ? -1 : b === "★" ? 1 : 0).map(([emoji, count]) => {

          const emojiKey = emoji.startsWith(":") && emoji.endsWith(":") ? emoji.slice(1, -1) : emoji;
          const isCustomEmoji = emoji.startsWith(":") && emoji.endsWith(":");

          const isMapLoaded = Object.keys(emojiMap).length > 0;
          const emojiIsRemote = isCustomEmoji && isMapLoaded && !localEmojiMap[emojiKey];
          return (
            <span
              key={emoji}
               className={`reaction-badge${myReaction === emoji ? " active" : ""}`}
              onClick={async () => {
                // 💡 원격 에모지라면 클릭 시 즉시 리턴하여 백엔드 요청을 방어합니다.
                if (emojiIsRemote) return;
                onToggle(emoji);
              }}
              onMouseEnter={(e) => {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                if (tooltipTimerRef.current) clearTimeout(tooltipTimerRef.current);
                tooltipTimerRef.current = setTimeout(() => {
                  api.reactionUsers(targetId, emoji).then((d) => {
                    if (d.users.length > 0) {
                      setReactionTooltip({ emoji, users: d.users, x: rect.left + rect.width / 2, y: rect.top - 6 });
                    }
                  }).catch(() => {});
                }, 300);
              }}
              onMouseLeave={() => {
                if (tooltipTimerRef.current) clearTimeout(tooltipTimerRef.current);
                setReactionTooltip(null);
              }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                padding: "2px 8px",
                borderRadius: 12,
                fontSize: 13,
                cursor: emojiIsRemote ? "default" : "pointer", // 원격이면 커서 기본값
                border: "1px solid var(--border)",
                background: myReaction === emoji ? "color-mix(in srgb, var(--accent) 20%, transparent)" : "var(--bg-secondary)",
                opacity: 1
              }}
            >
              {emoji === "★" ? (
                <Icon name="star_filled" size={18} style={{ color: "#f1c40f" }} />
              ) : emojiMap[emojiKey] ? (
                <img src={emojiMap[emojiKey]} alt={emoji} style={{ height: 22, verticalAlign: "middle" }} />
              ) : (
                <span>{emoji}</span>
              )}
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{typeof count === "number" ? count : 0}</span>
            </span>
          );
        })}
      </div>
      {reactionTooltip && (
        <div style={{
          position: "fixed",
          left: reactionTooltip.x,
          top: reactionTooltip.y,
          transform: "translate(-50%, -100%)",
          background: "var(--bg-primary)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: "6px 10px",
          fontSize: 12,
          color: "var(--text-primary)",
          zIndex: 9999,
          pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
          lineHeight: 1.4,
        }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexWrap: "wrap", maxWidth: 260 }}>
            {reactionTooltip.users.slice(0, 3).map((u) => (
              <span key={u.id} style={{ display: "inline-flex", alignItems: "center", gap: 3, whiteSpace: "nowrap" }}>
                <Avatar user={u} style={{ width: 16, height: 16, borderRadius: 4, verticalAlign: "middle" }} />
                {u.display_name || u.username}
              </span>
            )).reduce((acc, el, i) => {
              if (i > 0) acc.push(<span key={`,${i}`} style={{ color: "var(--text-muted)" }}>,</span>);
              acc.push(el);
              return acc;
            }, [] as React.ReactNode[])}
            {reactionTooltip.users.length > 3 && <span style={{ color: "var(--text-muted)" }}> 외 {reactionTooltip.users.length - 3}명</span>}
          </span>
        </div>
      )}
    </>
  );
}
