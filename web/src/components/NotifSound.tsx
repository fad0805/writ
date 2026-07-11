"use client";
import { useEffect, useRef } from "react";

export default function NotifSound() {
  const readyRef = useRef(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const bufRef = useRef<AudioBuffer | null>(null);

  useEffect(() => {
    const init = async () => {
      if (readyRef.current) return;
      try {
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        if (ctx.state === "suspended") await ctx.resume();
        const resp = await fetch("/alert.wav");
        const ab = await resp.arrayBuffer();
        const decoded = await ctx.decodeAudioData(ab);
        ctxRef.current = ctx;
        bufRef.current = decoded;
        readyRef.current = true;
      } catch {}
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
      if (!readyRef.current || !ctxRef.current || !bufRef.current) return;
      try {
        const ctx = ctxRef.current;
        if (ctx.state === "suspended") ctx.resume();
        const src = ctx.createBufferSource();
        src.buffer = bufRef.current;
        src.connect(ctx.destination);
        src.start();
      } catch {}
    };
    es.onerror = () => {};
    return () => { es.close(); document.removeEventListener("click", unlock); document.removeEventListener("keydown", unlock); };
  }, []);

  return null;
}
