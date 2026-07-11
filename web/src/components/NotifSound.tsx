"use client";
import { useEffect, useRef } from "react";

export default function NotifSound() {
  const audioRef = useRef<{ ctx: AudioContext; buf: AudioBuffer | null } | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/notifications/stream");
    es.onmessage = async () => {
      try {
        if (!audioRef.current) {
          const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
          const resp = await fetch("/alert.aiff");
          const buf = await resp.arrayBuffer();
          const decoded = await ctx.decodeAudioData(buf);
          audioRef.current = { ctx, buf: decoded };
        }
        const { ctx, buf } = audioRef.current;
        if (!buf) return;
        if (ctx.state === "suspended") await ctx.resume();
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);
        src.start();
      } catch {}
    };
    es.onerror = () => {};
    return () => es.close();
  }, []);

  return null;
}
