"use client";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Icon from "@/components/Icon";

const EXPORT_TYPES = [
  { key: "follows", label: "팔로우", icon: "user_solid" },
  { key: "mutes", label: "뮤트", icon: "mute" },
  { key: "blocks", label: "차단", icon: "block" },
  { key: "domain_blocks", label: "도메인 차단", icon: "globe" },
  { key: "bookmarks", label: "북마크", icon: "star_filled" },
  { key: "keyword_mutes", label: "키워드 필터", icon: "tag" },
  { key: "posts", label: "게시글", icon: "edit" },
];

export default function DeactivatedPage() {
  const router = useRouter();
  const { user, refresh } = useAuth();

  if (!user) return null;
  if (!(user as any).is_deactivated) {
    router.replace("/timeline/home");
    return null;
  }

  return (
    <div style={{ maxWidth: 520, margin: "60px auto", padding: "0 16px" }}>
      <div style={{ textAlign: "center", marginBottom: 32 }}>
        <div style={{ fontSize: 48, marginBottom: 16, color: "var(--danger)" }}>⚠</div>
        <h2 style={{ marginBottom: 8 }}>계정 비활성화</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.6 }}>
          이 계정은 이전되어 비활성화된 상태입니다.
          비활성화를 해제하거나 데이터를 내려받을 수 있습니다.
        </p>
      </div>

      <div className="novel-form" style={{ borderColor: "var(--danger)" }}>
        <div className="form-group">
          <label>비활성화 해제</label>
          <p className="form-help" style={{ marginBottom: 8 }}>계정을 다시 활성화하면 모든 기능을 다시 사용할 수 있습니다. 다시 로그인해야 합니다.</p>
          <button onClick={async () => {
            if (!confirm("계정을 다시 활성화하시겠습니까?")) return;
            try {
              const res = await fetch("/api/settings/reactivate", { method: "POST", credentials: "include" });
              if (res.ok) { await refresh(); router.replace("/timeline/home"); }
              else alert("실패");
            } catch { alert("오류"); }
          }} className="btn btn-primary">비활성화 해제</button>
        </div>

        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>데이터 내려받기</label>
          <p className="form-help" style={{ marginBottom: 8 }}>
            각 항목을 개별 CSV 파일로 내려받을 수 있습니다. Mastodon 등 다른 ActivityPub 서버에 업로드하여 가져올 수 있습니다.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {EXPORT_TYPES.map((t) => (
              <a key={t.key} href={`/api/settings/export/${t.key}`} className="btn btn-outline" style={{ justifyContent: "flex-start", fontSize: 14 }} download>
                <Icon name={t.icon} size={14} /> {t.label}
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
