"use client";
import Link from "next/link";
import Icon from "./Icon";

export default function SettingsNav({ current }: { current: "visibility" | "account" }) {
  return (
    <div style={{ display: "flex", gap: 16, marginBottom: 20, fontSize: "0.85em", color: "var(--text-muted)" }}>
      <div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>개인 설정</div>
        <div style={{ display: "flex", gap: 6 }}>
          <Link href="/users/settings" className={`btn btn-small ${current === "visibility" ? "btn-primary" : "btn-outline"}`}>공개 설정</Link>
          <Link href="/users/settings/account" className={`btn btn-small ${current === "account" ? "btn-primary" : "btn-outline"}`}>계정 관리</Link>
        </div>
      </div>
    </div>
  );
}
