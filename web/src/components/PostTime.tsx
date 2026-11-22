"use client";
import React from "react";
import Link from "next/link";
import { useNow } from "@/hooks/useNow";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function formatPostTime(createdAt: string | null, now: number): string {
  if (!createdAt) return "";
  const t = new Date(createdAt).getTime();
  if (!Number.isFinite(t)) return "";
  const diff = Math.max(0, now - t);
  if (diff < DAY) {
    if (diff < MINUTE) return `${Math.floor(diff / 1000)}초 전`;
    if (diff < HOUR) return `${Math.floor(diff / MINUTE)}분 전`;
    return `${Math.floor(diff / HOUR)}시간 전`;
  }
  return new Date(t).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).replace(/\. /g, "-").replace(/\.$/, "");
}

function refreshInterval(createdAt: string | null): number {
  if (!createdAt) return 0;
  const t = new Date(createdAt).getTime();
  if (!Number.isFinite(t)) return 0;
  const age = Date.now() - t;
  if (age < MINUTE) return 1000;
  if (age < HOUR) return 10_000;
  if (age < DAY) return 60_000;
  return 0;
}

/** 작성 시각만 갱신하는 작은 컴포넌트 — 카드 전체가 다시 렌더링되지 않는다. */
export default React.memo(function PostTime({ createdAt, href }: { createdAt: string | null; href: string }) {
  const interval = refreshInterval(createdAt);
  const now = useNow(interval || 60_000, interval > 0);
  const text = formatPostTime(createdAt, now);
  if (!text) return null;
  return <Link href={href} className="no-underline" style={{ color: "inherit" }}>{text}</Link>;
});
