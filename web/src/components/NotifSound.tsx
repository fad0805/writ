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
          }
          if ((parsed.sound || (parsed.unread !== undefined && parsed.unread > 0)) && audioRef.current && isNotifSoundEnabled()) {
            audioRef.current.currentTime = 0;
            audioRef.current.play().catch(() => {});
          }
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  return null;
}
