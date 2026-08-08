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
  const positionsRef = useRef<Record<string, number>>({});

  useEffect(() => {
    history.scrollRestoration = "manual";
    positionsRef.current = getPositions();

    const container = document.querySelector(".main-content");
    if (!container) return;

    const key = prevPath.current;
    const saved = positionsRef.current[key];
    if (saved) {
      restoreScroll(container as HTMLElement, saved);
    }

    const onScroll = () => {
      positionsRef.current[prevPath.current] = container.scrollTop;
    };
    container.addEventListener("scroll", onScroll, { passive: true });

    const save = () => {
      try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify(positionsRef.current)); } catch {}
    };
    window.addEventListener("pagehide", save);
    return () => {
      save();
      container.removeEventListener("scroll", onScroll);
      window.removeEventListener("pagehide", save);
      history.scrollRestoration = "auto";
    };
  }, []);

  useEffect(() => {
    const container = document.querySelector(".main-content");
    if (prevPath.current === pathname) return;

    const key = prevPath.current;
    if (container && container.scrollTop > 0) {
      positionsRef.current[key] = container.scrollTop;
    }

    prevPath.current = pathname;
    try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify(positionsRef.current)); } catch {}
    const saved = positionsRef.current[pathname];
    if (saved && container) {
      restoreScroll(container as HTMLElement, saved);
    } else {
      container?.scrollTo(0, 0);
    }
  }, [pathname]);

  return null;
}
