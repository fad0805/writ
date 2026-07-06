"use client";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import { PostData, User } from "@/lib/api";
import PostCard from "@/components/PostCard";
import EmojiPicker from "@/components/EmojiPicker";

export default function DirectConversationPage() {
  const params = useParams();
  const router = useRouter();
  const [otherUser, setOtherUser] = useState<User | null>(null);
  const [messages, setMessages] = useState<PostData[]>([]);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const loadIdRef = useRef(0);

  const load = useCallback(async () => {
    const id = ++loadIdRef.current;
    const otherId = Array.isArray(params.id) ? params.id[0] : params.id;
    if (!otherId) return;
    try {
      const res = await fetch(`/api/direct/conversation/${otherId}`, { credentials: "include" });
      const d = await res.json();
      if (id !== loadIdRef.current) return;
      setOtherUser(d.other_user);
      setMessages(d.messages || []);
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    } catch { if (id === loadIdRef.current) setLoading(false); }
  }, [params.id]);

  useEffect(() => { load(); }, [load]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending || !otherUser) return;
    setSending(true);
    try {
      const form = new FormData();
      if (otherUser.is_remote && messages.length > 0) {
        const mention = `@${otherUser.username} `;
        form.append("content", input.startsWith("@") ? input : mention + input);
        form.append("parent_id", String(messages[messages.length - 1].id));
        form.append("visibility", "mention");
      } else {
        form.append("content", input);
        form.append("visibility", "mention");
        form.append("dm_target_id", String(otherUser.id));
      }

      const res = await fetch("/api/posts", { method: "POST", credentials: "include", body: form });
      if (res.ok) { setInput(""); await load(); }
    } catch {}
    setSending(false);
  };

  return (
    <div className="dm-container">
      <div className="dm-header">
        <button onClick={() => { sessionStorage.setItem("notif_filter", "direct"); router.push("/notifications"); }} className="dm-header-back">←</button>
        <span className="dm-header-name">💬 {otherUser?.display_name || "..."}</span>
      </div>
      <div className="dm-messages">
        {loading ? (
          <div className="empty-state">로딩 중...</div>
        ) : messages.length === 0 ? (
          <div className="empty-state">대화 내역이 없습니다.</div>
        ) : messages.map((m) => (
          <div key={m.id} className="dm-message-wrap" style={{ alignItems: m.is_mine ? "flex-end" : "flex-start" }}>
            <div className="dm-message-bubble">
              <PostCard post={m} hideContext onUpdate={load} />
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={handleSend} className="dm-form">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={otherUser ? `${otherUser.display_name}에게 메시지 보내기` : ""}
          className="dm-input"
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { (e.target as HTMLElement).closest('form')?.requestSubmit(); } }}
          autoFocus
        />
        <div className="dm-emoji-wrap">
          <EmojiPicker onEmoji={(e) => setInput(input + e)} dropUp />
        </div>
        <button type="submit" disabled={sending || !input.trim()} className="btn btn-primary">전송</button>
      </form>
    </div>
  );
}
