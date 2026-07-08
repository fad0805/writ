export default function LoadingScreen({ message = "로딩 중..." }: { message?: string }) {
  return <div className="empty-state" style={{ padding: "60px 20px" }}>{message}</div>;
}
