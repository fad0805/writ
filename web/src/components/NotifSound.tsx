"use client";
import { useEffect, useRef } from "react";

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
    es.onmessage = () => {
      try {
        if (audioRef.current) {
          audioRef.current.currentTime = 0;
          audioRef.current.play().catch(() => {});
        }
        if (document.hidden && Notification.permission === "granted") {
          new Notification("WRIT", { body: "새 알림이 있습니다", icon: "/icons/icon-192.png", silent: true });
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  return null;
}
