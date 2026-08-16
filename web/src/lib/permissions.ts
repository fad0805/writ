export type Perm = string;

export const PERMS = {
  usersAdmin: "users.admin",
  settingsManage: "settings.manage",
  federationMode: "federation.mode",
  rolesManage: "roles.manage",
  usersManage: "users.manage",
  contentManage: "content.manage",
  reportsManage: "reports.manage",
  rulesManage: "rules.manage",
  announcementsManage: "announcements.manage",
  emojisManage: "emojis.manage",
  domainsManage: "domains.manage",
  federationManage: "federation.manage",
  logView: "log.view",
} as const;

export interface PermUser {
  role?: string;
  permissions?: string[];
}

export function can(user: PermUser | null | undefined, permission: string): boolean {
  if (!user) return false;
  if (user.role === "owner") return true;
  return !!user.permissions?.includes(permission);
}

export function isStaff(user: PermUser | null | undefined): boolean {
  if (!user) return false;
  if (user.role === "owner") return true;
  return (user.permissions?.length ?? 0) > 0;
}
