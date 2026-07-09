"use client";
import { useEffect, useState } from "react";
import Icon from "@/components/Icon";

interface Rule {
  id: number;
  title: string;
  description: string;
  sort_order: number;
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/rules")
      .then((r) => r.json())
      .then((d) => { setRules(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <p className="empty-state">로딩 중...</p>;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ marginBottom: 8 }}><Icon name="shield" /> 서버 규칙</h1>
      <p style={{ color: "var(--text-secondary)", marginBottom: 24, fontSize: 14 }}>
        아래 규칙을 위반할 경우 신고 대상이 될 수 있습니다.
      </p>
      {rules.length === 0 ? (
        <p className="empty-state">등록된 규칙이 없습니다.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {rules.map((rule, idx) => (
            <div key={rule.id} style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <span style={{ fontWeight: 700, fontSize: 13, color: "var(--text-muted)", minWidth: 24, marginTop: 2 }}>{idx + 1}.</span>
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{rule.title}</div>
                  {rule.description && <div style={{ fontSize: 14, color: "var(--text-secondary)", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{rule.description}</div>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
