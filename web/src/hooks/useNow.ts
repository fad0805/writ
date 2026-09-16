"use client";
import { useEffect, useState } from "react";

type Listener = () => void;

const registry = new Map<number, { listeners: Set<Listener>; id: ReturnType<typeof setInterval> | null }>();

let visPaused = false;
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    visPaused = document.hidden;
  });
}

function start(ms: number) {
  let bucket = registry.get(ms);
  if (!bucket) {
    bucket = { listeners: new Set(), id: null };
    registry.set(ms, bucket);
  }
  if (bucket.id !== null) return;
  bucket.id = setInterval(() => {
    if (visPaused) return;
    for (const fn of bucket.listeners) fn();
  }, ms);
}

function stop(ms: number) {
  const bucket = registry.get(ms);
  if (!bucket) return;
  if (bucket.listeners.size === 0 && bucket.id !== null) {
    clearInterval(bucket.id);
    bucket.id = null;
    registry.delete(ms);
  }
}

export function useNow(intervalMs = 10000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const listener = () => setNow(Date.now());
    const bucket = registry.get(intervalMs);
    if (bucket) bucket.listeners.add(listener);
    else registry.set(intervalMs, { listeners: new Set([listener]), id: null });
    start(intervalMs);
    return () => {
      const b = registry.get(intervalMs);
      b?.listeners.delete(listener);
      stop(intervalMs);
    };
  }, [intervalMs, enabled]);
  return now;
}
