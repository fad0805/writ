"use client";
import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "./Icon";
import { subscribeAnnouncementStatus } from "@/lib/announcements";

const TOAST_DURATION = 8000;

interface Popup {
  id: number;
  title: string;
}

export default function AnnouncementToast() {
  const router = useRouter();
  const { user } = useAuth();
  const [current, setCurrent] = useState<Popup | null>(null);
  const queueRef = useRef<Popup[]>([]);
  const shownRef = useRef<Set<number>>(new Set());
  const currentRef = useRef<Popup | null>(null);

  useEffect(() => { currentRef.current = current; }, [current]);

  const markNotified = useCallback(async (id: number) => {
    fetch(`/api/announcements/${id}/notified`, { method: "POST", credentials: "include" }).catch(() => {});
  }, []);

  const showNext = useCallback(() => {
    const next = queueRef.current.shift();
    setCurrent(next || null);
    if (next) markNotified(next.id);
    window.dispatchEvent(new Event("announcementchange"));
  }, [markNotified]);

  useEffect(() => {
    if (!user) return;
    const unsubscribe = subscribeAnnouncementStatus((status) => {
      const unseen = status.popups.filter((p) => !shownRef.current.has(p.id));
      for (const p of unseen) shownRef.current.add(p.id);
      if (unseen.length > 0) {
        queueRef.current.push(...unseen);
        if (currentRef.current === null) showNext();
      }
    });
    return () => unsubscribe();
  }, [user, showNext]);

  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => {
      showNext();
    }, TOAST_DURATION);
    return () => clearTimeout(t);
  }, [current, showNext]);

  if (!current) return null;

  return (
    <div className="announcement-toast-wrap">
      <div
        className="announcement-toast"
        role="button"
        tabIndex={0}
        onClick={() => {
          const id = current.id;
          queueRef.current = [];
          setCurrent(null);
          router.push(`/announcements/${id}`);
        }}
        onKeyDown={(e) => { if (e.key === "Enter") { const id = current.id; queueRef.current = []; setCurrent(null); router.push(`/announcements/${id}`); } }}
      >
        <Icon name="star_filled" size={16} style={{ color: "#f1c40f", flexShrink: 0 }} />
        <span className="announcement-toast-title">{current.title}</span>
        <button
          className="announcement-toast-close"
          onClick={(e) => { e.stopPropagation(); showNext(); }}
          aria-label="닫기"
        >
          <Icon name="x" size={14} />
        </button>
      </div>
    </div>
  );
}
