"use client";
import { useRef, useState, useEffect, useCallback } from "react";

export default function AudioPlayer({ src, className }: { src: string; className?: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seeking, setSeeking] = useState(false);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => { if (!seeking) setCurrent(a.currentTime); };
    const onDur = () => setDuration(a.duration || 0);
    const onEnd = () => setPlaying(false);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onDur);
    a.addEventListener("ended", onEnd);
    return () => { a.removeEventListener("timeupdate", onTime); a.removeEventListener("loadedmetadata", onDur); a.removeEventListener("ended", onEnd); };
  }, [seeking]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) { a.play(); setPlaying(true); } else { a.pause(); setPlaying(false); }
  }, []);

  const onSeek = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Number(e.target.value);
    setCurrent(v);
    if (audioRef.current) audioRef.current.currentTime = v;
  }, []);

  const fmt = (s: number) => {
    if (!isFinite(s)) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const pct = duration > 0 ? (current / duration) * 100 : 0;

  return (
    <div className={`audio-player${className ? ` ${className}` : ""}`}>
      <audio ref={audioRef} src={src} preload="metadata" />
      <button className="ap-play" onClick={toggle} type="button" aria-label={playing ? "Pause" : "Play"}>
        {playing ? (
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>
        ) : (
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M8 5.14v14.72a1 1 0 0 0 1.5.86l11.5-7.36a1 1 0 0 0 0-1.72L9.5 4.28A1 1 0 0 0 8 5.14z"/></svg>
        )}
      </button>
      <span className="ap-time">{fmt(current)}</span>
      <input
        className="ap-seek"
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        value={current}
        onMouseDown={() => setSeeking(true)}
        onMouseUp={() => setSeeking(false)}
        onTouchStart={() => setSeeking(true)}
        onTouchEnd={() => setSeeking(false)}
        onChange={onSeek}
        style={{ background: `linear-gradient(to right, var(--accent) ${pct}%, var(--border) ${pct}%)` }}
      />
      <span className="ap-time">{fmt(duration)}</span>
    </div>
  );
}
