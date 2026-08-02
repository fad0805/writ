"use client";
import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

const SCROLL_KEY = "scroll_positions";

function getPositions(): Record<string, number> {
  try { return JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "{}"); } catch { return {}; }
}

function restoreScroll(container: HTMLElement, target: number) {
  const maxScroll = container.scrollHeight - container.clientHeight;
  if (maxScroll >= target) {
    container.scrollTo(0, target);
    return;
  }
  let retries = 0;
  const observer = new ResizeObserver(() => {
    const ms = container.scrollHeight - container.clientHeight;
    if (ms >= target || retries > 30) {
      container.scrollTo(0, Math.min(target, ms));
      observer.disconnect();
    }
    retries++;
  });
  observer.observe(container);
  setTimeout(() => observer.disconnect(), 3000);
}

export default function ScrollRestoration() {
  const pathname = usePathname();
  const prevPath = useRef(pathname);

  useEffect(() => {
    history.scrollRestoration = "manual";

    const container = document.querySelector(".main-content");
    if (!container) return;

    const key = prevPath.current;
    const saved = getPositions()[key];
    if (saved) {
      restoreScroll(container as HTMLElement, saved);
    }

    const onScroll = () => {
      const positions = getPositions();
      positions[prevPath.current] = container.scrollTop;
      sessionStorage.setItem(SCROLL_KEY, JSON.stringify(positions));
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const container = document.querySelector(".main-content");
    if (prevPath.current === pathname) return;

    const key = prevPath.current;
    if (container && container.scrollTop > 0) {
      const positions = getPositions();
      positions[key] = container.scrollTop;
      sessionStorage.setItem(SCROLL_KEY, JSON.stringify(positions));
    }

    prevPath.current = pathname;
    const saved = getPositions()[pathname];
    if (saved && container) {
      restoreScroll(container as HTMLElement, saved);
    } else {
      container?.scrollTo(0, 0);
    }
  }, [pathname]);

  return null;
}
