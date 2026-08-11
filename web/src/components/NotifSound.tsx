"use client";
import { useEffect, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { onNotificationStream } from "@/lib/notificationStream";

const LS_KEY = "writ_notif_sound";

export function isNotifSoundEnabled(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem(LS_KEY) !== "off";
}

export function setNotifSoundEnabled(on: boolean) {
  localStorage.setItem(LS_KEY, on ? "on" : "off");
}

export default function NotifSound() {
  const { user } = useAuth();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const prevUnreadRef = useRef<number>(0);

  useEffect(() => {
    prevUnreadRef.current = 0;
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

    const unsubscribe = onNotificationStream((raw) => {
      try {
        if (raw === "refresh") return;
        const parsed = JSON.parse(raw);
        if (parsed && parsed.event === "notif") {
          if (parsed.unread !== undefined) {
            const badge = document.querySelector(".notif-badge");
            if (badge) badge.textContent = String(parsed.unread);
            if (typeof window !== "undefined") (window as unknown as { __unreadNotifs?: number }).__unreadNotifs = parsed.unread;
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
    });
    return () => { unsubscribe(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, [user?.id]);

  return null;
}
