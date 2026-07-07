"use client";
import Link from "next/link";
import Icon from "./Icon";

export default function AdminNav({ current }: { current: "dashboard" | "reports" | "users" | "emojis" | "settings" }) {
  return (
    <>
      <div className="admin-tabs">
        <Link href="/admin" className={`btn btn-small ${current === "dashboard" ? "btn-primary" : "btn-outline"}`}>대시보드</Link>
      </div>
      <div style={{ display: "flex", gap: 16, marginBottom: 20, fontSize: "0.85em", color: "var(--text-muted)" }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>중재</div>
          <div style={{ display: "flex", gap: 6 }}>
            <Link href="/admin/users" className={`btn btn-small ${current === "users" ? "btn-primary" : "btn-outline"}`}>유저 관리</Link>
            <Link href="/admin/reports" className={`btn btn-small ${current === "reports" ? "btn-primary" : "btn-outline"}`}>신고 관리</Link>
          </div>
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>관리</div>
          <div style={{ display: "flex", gap: 6 }}>
            <Link href="/admin/emojis" className={`btn btn-small ${current === "emojis" ? "btn-primary" : "btn-outline"}`}>커스텀 이모지</Link>
            <Link href="/admin/settings" className={`btn btn-small ${current === "settings" ? "btn-primary" : "btn-outline"}`}>서버 정보</Link>
          </div>
        </div>
      </div>
    </>
  );
}
