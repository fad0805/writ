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
    es.onmessage = () => {
      try {
        if (audioRef.current && isNotifSoundEnabled()) {
          audioRef.current.currentTime = 0;
          audioRef.current.play().catch(() => {});
        }
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  return null;
}
