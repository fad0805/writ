"use client";
import { useEffect, useState } from "react";
import type { WindowWithGlobals } from "@/lib/windowGlobals";

export default function Loading({ text = "로딩 중..." }: { text?: string }) {
  const [logo, setLogo] = useState("");

  useEffect(() => {
    const win = window as WindowWithGlobals;
    const cached = win.__serverLogo;
    if (cached !== undefined) {
      const id = setTimeout(() => setLogo(cached), 0);
      return () => clearTimeout(id);
    }
    let cancelled = false;
    fetch("/api/server-info").then((r) => r.json()).then((d) => {
      const newLogo = d.logo || "";
      win.__serverLogo = newLogo;
      if (!cancelled) setLogo(newLogo);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="empty-state">
      {logo ? <img src={logo} alt="" style={{ width: 48, height: 48, marginBottom: 12, objectFit: "contain" }} /> : null}
      <br />{text}
    </div>
  );
}
