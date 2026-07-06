"use client";
import Link from "next/link";

export default function DirectUserCard({ user }: { user: { id: number; username: string; display_name: string; latest_previews?: { text: string; is_me: boolean }[]; latest_time?: string } }) {
  return (
    <Link href={`/direct/${user.id}`} className="direct-user-card">
      <div
        className="direct-user-avatar"
        style={{ background: `hsl(${user.username?.length * 37 % 360}, 35%, 40%)` }}
      >
        {(user.display_name || user.username)[0]}
      </div>
      <div className="novel-card-body-content">
        <div className="direct-user-name">{user.display_name}</div>
        <div className="direct-user-handle">@{user.username}</div>
      </div>
      {user.latest_previews && user.latest_previews.length > 0 && (
        <div style={{ textAlign: "right", flexShrink: 0, maxWidth: "40%" }}>
          {user.latest_previews.slice(0, 3).map((item, i) => (
            <div key={i} style={{ fontSize: "0.8em", color: item.is_me ? "var(--accent)" : "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.5 }}>
              {item.text || "(내용 없음)"}
            </div>
          ))}
        </div>
      )}
    </Link>
  );
}
