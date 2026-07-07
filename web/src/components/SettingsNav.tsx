"use client";
import Link from "next/link";
import Icon from "./Icon";

export default function SettingsNav({ current }: { current: "visibility" | "account" }) {
  return (
    <div className="admin-tabs">
      <Link href="/users/settings" className={`btn btn-small ${current === "visibility" ? "btn-primary" : "btn-outline"}`}>공개 설정</Link>
      <Link href="/users/settings/account" className={`btn btn-small ${current === "account" ? "btn-primary" : "btn-outline"}`}>계정 관리</Link>
    </div>
  );
}
