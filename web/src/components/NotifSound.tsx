"use client";
import { useEffect, useRef } from "react";

const LS_KEY = "writ_notif_sound";

export function isNotifSoundEnabled(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem(LS_KEY) !== "off";
}

export function setNotifSoundEnabled(on: boolean) {
  localStorage.setItem(LS_KEY, on ? "on" : "off");
}

export default function NotifSound() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const prevUnreadRef = useRef<number>(0);

  useEffect(() => {
    const init = () => {
      if (audioRef.current) return;
      audioRef.current = new Audio("/alert.wav");
      audioRef.current.volume = 0.5;
    };

    const unlock = () => {
      document.removeEventListener("click", unlock);
      document.removeEventListener("keydown", unlock);
      init();
    };
    document.addEventListener("click", unlock);
    document.addEventListener("keydown", unlock);

    const es = new EventSource("/api/notifications/stream");
    es.onmessage = (event) => {
      try {
        if (event.data === "refresh") return;
        const parsed = JSON.parse(event.data);
        if (parsed && parsed.event === "notif") {
          if (parsed.unread !== undefined) {
            const badge = document.querySelector(".notif-badge");
            if (badge) badge.textContent = String(parsed.unread);
            if (typeof window !== "undefined") (window as any).__unreadNotifs = parsed.unread;
            window.dispatchEvent(new Event("notifchange"));
          }
          if (parsed.sound && audioRef.current && isNotifSoundEnabled()) {
            const curUnread = typeof parsed.unread === "number" ? parsed.unread : (prevUnreadRef.current + 1);
            if (curUnread > prevUnreadRef.current) {
              audioRef.current.currentTime = 0;
              audioRef.current.play().catch(() => {});
            }
            if (typeof parsed.unread === "number") prevUnreadRef.current = parsed.unread;
          } else if (typeof parsed.unread === "number") {
            prevUnreadRef.current = parsed.unread;
          }
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  return null;
}
