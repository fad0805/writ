"use client";
import { useEffect } from "react";

export default function ConfirmModal({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div className="reply-modal-backdrop active" onClick={onCancel}>
      <div className="reply-modal" onClick={(e) => e.stopPropagation()} style={{ width: "min(380px, 100%)", textAlign: "center" }}>
        <p style={{ margin: "20px 0", color: "var(--text-primary)" }}>{message}</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button className="btn btn-primary" onClick={onConfirm}>확인</button>
          <button className="btn btn-outline" onClick={onCancel}>취소</button>
        </div>
      </div>
    </div>
  );
}
