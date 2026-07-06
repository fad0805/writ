import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty-state">
      <Link href="/timeline/home" className="not-found-link">
        <span className="not-found-logo" />
      </Link>
      <h1 className="not-found-title">404</h1>
      <p className="text-secondary" style={{ margin: 0 }}>페이지를 찾을 수 없습니다.</p>
    </div>
  );
}
