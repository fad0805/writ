"use client";
import Link from "next/link";
import Icon from "./Icon";

export default function SettingsNav({ current }: { current: "visibility" | "account" | "mutes" | "migrate" | "data" }) {
  return (
    <div className="admin-tabs">
      <Link href="/users/settings" className={`btn btn-small ${current === "visibility" ? "btn-primary" : "btn-outline"}`}>기본 설정</Link>
      <Link href="/users/settings/account" className={`btn btn-small ${current === "account" ? "btn-primary" : "btn-outline"}`}>정보 관리</Link>
      <Link href="/users/settings/mutes" className={`btn btn-small ${current === "mutes" ? "btn-primary" : "btn-outline"}`}>차단/뮤트</Link>
      <Link href="/users/settings/data" className={`btn btn-small ${current === "data" ? "btn-primary" : "btn-outline"}`}>내보내기/가져오기</Link>
      <Link href="/users/settings/migrate" className={`btn btn-small ${current === "migrate" ? "btn-primary" : "btn-outline"}`}>계정 이전</Link>
    </div>
  );
}
