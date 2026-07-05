import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty-state" style={{ padding: "4rem 2rem", textAlign: "center" }}>
      <Link href="/timeline/home" style={{ display: "inline-block", marginBottom: "1.5rem" }}>
        <span style={{ display: "inline-block", width: 48, height: 48, backgroundColor: "var(--accent)", mask: "url(/logo.svg) center/contain no-repeat", WebkitMask: "url(/logo.svg) center/contain no-repeat" }} />
      </Link>
      <h1 style={{ fontSize: "3rem", margin: "0 0 0.5rem" }}>404</h1>
      <p style={{ color: "var(--text-secondary)", margin: 0 }}>페이지를 찾을 수 없습니다.</p>
    </div>
  );
}
