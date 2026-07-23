"use client";
import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

const SCROLL_KEY = "scroll_positions";

function getPositions(): Record<string, number> {
  try { return JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "{}"); } catch { return {}; }
}

export default function ScrollRestoration() {
  const pathname = usePathname();
  const prevPath = useRef(pathname);

  useEffect(() => {
    const container = document.querySelector(".main-content");
    if (!container) return;

    const key = prevPath.current;
    const saved = getPositions()[key];
    if (saved) {
      requestAnimationFrame(() => container.scrollTo(0, saved));
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
    if (saved) {
      requestAnimationFrame(() => container?.scrollTo(0, saved));
    } else {
      container?.scrollTo(0, 0);
    }
  }, [pathname]);

  return null;
}
