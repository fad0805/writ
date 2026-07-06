import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty-state" style={{ padding: "4rem 2rem", textAlign: "center" }}>
      <Link href="/timeline/home" className="not-found-link">
        <span className="not-found-logo" />
      </Link>
      <h1 style={{ fontSize: "3rem", margin: "0 0 0.5rem" }}>404</h1>
      <p style={{ color: "var(--text-secondary)", margin: 0 }}>페이지를 찾을 수 없습니다.</p>
    </div>
  );
}
