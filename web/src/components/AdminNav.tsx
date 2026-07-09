"use client";
import Link from "next/link";
import Icon from "./Icon";

export default function AdminNav({ current }: { current: "dashboard" | "reports" | "users" | "emojis" | "settings" | "federation" | "moderation-log" | "blocked-domains" | "rules" }) {
  return (
    <>
      <div className="admin-tabs">
        <Link href="/admin" className={`btn btn-small ${current === "dashboard" ? "btn-primary" : "btn-outline"}`}>서버 관리</Link>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 20 }}>
        <Link href="/admin/users" className={`btn btn-small ${current === "users" ? "btn-primary" : "btn-outline"}`}>유저 관리</Link>
        <Link href="/admin/reports" className={`btn btn-small ${current === "reports" ? "btn-primary" : "btn-outline"}`}>신고 관리</Link>
        <Link href="/admin/federation" className={`btn btn-small ${current === "federation" ? "btn-primary" : "btn-outline"}`}>연합</Link>
        <Link href="/admin/moderation-log" className={`btn btn-small ${current === "moderation-log" ? "btn-primary" : "btn-outline"}`}>중재 기록</Link>
        <Link href="/admin/blocked-domains" className={`btn btn-small ${current === "blocked-domains" ? "btn-primary" : "btn-outline"}`}>도메인 차단</Link>
        <Link href="/admin/rules" className={`btn btn-small ${current === "rules" ? "btn-primary" : "btn-outline"}`}>규칙</Link>
        <Link href="/admin/settings" className={`btn btn-small ${current === "settings" ? "btn-primary" : "btn-outline"}`}>서버 정보</Link>
        <Link href="/admin/emojis" className={`btn btn-small ${current === "emojis" ? "btn-primary" : "btn-outline"}`}>커스텀 이모지</Link>
      </div>
    </>
  );
}
