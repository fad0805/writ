export interface Announcement {
  id: number;
  title: string;
  content: string;
  starts_at: string | null;
  ends_at: string | null;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  active?: boolean;
  is_read?: boolean;
  notified?: boolean;
}

export interface AnnouncementStatus {
  has_active: boolean;
  unread_count: number;
  popups: { id: number; title: string }[];
}

// _fmt_dt returns KST ISO like "2026-08-02T15:30:00+09:00"
export function toInputValue(iso?: string | null): string {
  if (!iso) return "";
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  if (!m) return "";
  return `${m[1]}T${m[2]}:${m[3]}`;
}

export function fmtAnnouncementTime(iso?: string | null): string {
  if (!iso) return "";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return "";
  return `${m[1]}.${m[2]}.${m[3]} ${m[4]}:${m[5]}`;
}

export async function fetchAnnouncementStatus(): Promise<AnnouncementStatus> {
  try {
    const res = await fetch("/api/announcements/status", { credentials: "include" });
    if (!res.ok) return { has_active: false, unread_count: 0, popups: [] };
    return await res.json();
  } catch {
    return { has_active: false, unread_count: 0, popups: [] };
  }
}
