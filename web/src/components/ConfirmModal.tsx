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
      <div className="reply-modal confirm-modal">
        <p className="confirm-message">{message}</p>
        <div className="confirm-buttons">
          <button className="btn btn-primary" onClick={onConfirm}>확인</button>
          <button className="btn btn-outline" onClick={onCancel}>취소</button>
        </div>
      </div>
    </div>
  );
}
