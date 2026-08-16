"use client";
import Link from "next/link";
import { can, PERMS, PermUser } from "@/lib/permissions";

type CurrentKey = "dashboard" | "reports" | "users" | "emojis" | "settings" | "federation" | "moderation-log" | "blocked-domains" | "rules" | "content" | "announcements" | "roles";

type Tab = { key: CurrentKey; href: string; label: string; perm: string };

const MOD_TABS: Tab[] = [
  { key: "users", href: "/admin/users", label: "유저 관리", perm: PERMS.usersManage },
  { key: "reports", href: "/admin/reports", label: "신고 관리", perm: PERMS.reportsManage },
  { key: "federation", href: "/admin/federation", label: "연합", perm: PERMS.federationManage },
  { key: "blocked-domains", href: "/admin/blocked-domains", label: "도메인 차단", perm: PERMS.domainsManage },
  { key: "rules", href: "/admin/rules", label: "규칙", perm: PERMS.rulesManage },
  { key: "moderation-log", href: "/admin/moderation-log", label: "중재 기록", perm: PERMS.logView },
  { key: "content", href: "/admin/content", label: "콘텐츠 관리", perm: PERMS.contentManage },
  { key: "announcements", href: "/admin/announcements", label: "공지사항", perm: PERMS.announcementsManage },
  { key: "roles", href: "/admin/roles", label: "역할", perm: PERMS.rolesManage },
];

const ADMIN_TABS: Tab[] = [
  { key: "settings", href: "/admin/settings", label: "서버 정보", perm: PERMS.settingsManage },
  { key: "emojis", href: "/admin/emojis", label: "커스텀 이모지", perm: PERMS.emojisManage },
];

export default function AdminNav({ current, user }: { current: CurrentKey; user?: PermUser | null }) {
  const modTabs = MOD_TABS.filter(t => can(user, t.perm));
  const adminTabs = ADMIN_TABS.filter(t => can(user, t.perm));
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>중재</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
        {modTabs.map(t => (
          <Link key={t.key} href={t.href} className={`btn btn-small ${current === t.key ? "btn-primary" : "btn-outline"}`}>{t.label}</Link>
        ))}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>관리</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 20 }}>
        {adminTabs.map(t => (
          <Link key={t.key} href={t.href} className={`btn btn-small ${current === t.key ? "btn-primary" : "btn-outline"}`}>{t.label}</Link>
        ))}
      </div>
    </>
  );
}
