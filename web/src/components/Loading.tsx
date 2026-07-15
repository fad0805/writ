"use client";
import { useEffect, useState } from "react";

export default function Loading({ text = "로딩 중..." }: { text?: string }) {
  const [logo, setLogo] = useState("");

  useEffect(() => {
    const cached = (window as any).__serverLogo;
    if (cached !== undefined) { setLogo(cached); return; }
    fetch("/api/server-info").then((r) => r.json()).then((d) => {
      const logo = d.logo || "";
      (window as any).__serverLogo = logo;
      setLogo(logo);
    }).catch(() => {});
  }, []);

  return (
    <div className="empty-state">
      {logo ? <img src={logo} alt="" style={{ width: 48, height: 48, marginBottom: 12, objectFit: "contain" }} /> : null}
      <br />{text}
    </div>
  );
}
