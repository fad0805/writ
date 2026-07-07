"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function NotFound() {
  const [logo, setLogo] = useState("");

  useEffect(() => {
    fetch("/api/server-info").then((r) => r.json()).then((d) => setLogo(d.logo || "")).catch(() => {});
  }, []);

  return (
    <div className="empty-state">
      <Link href="/timeline/home" className="not-found-link">
        {logo ? <img src={logo} alt="" className="not-found-logo-img" /> : <span className="not-found-logo" />}
      </Link>
      <h1 className="not-found-title">404</h1>
      <p className="text-secondary" style={{ margin: 0 }}>페이지를 찾을 수 없습니다.</p>
    </div>
  );
}
