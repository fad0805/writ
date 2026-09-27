"use client";
import Icon from "./Icon";
import { useLiveStreamStatus } from "@/lib/streamStatus";
import { useNotificationStreamStatus } from "@/lib/notificationStream";

// 실시간 스트리밍(SSE) 연결이 끊겼을 때 유저가 눈으로 알아챌 수 있도록
// 붉은 배너를 띄운다. EventSource가 재연결되면(open) 자동으로 사라진다.
export default function StreamStatusBanner() {
  const liveStatus = useLiveStreamStatus();
  const notifStatus = useNotificationStreamStatus();

  const labels: string[] = [];
  if (liveStatus === "down") labels.push("실시간");
  if (notifStatus === "down") labels.push("알림");

  if (labels.length === 0) return null;

  return (
    <div className="live-stream-banner" role="status" aria-live="polite">
      <Icon name="refresh" size={16} className="live-stream-banner-icon" />
      <span>
        <strong>{labels.join(", ")}</strong> 연결이 끊겼어요.
        자동으로 다시 연결 중이에요…
      </span>
      <button
        type="button"
        className="live-stream-banner-refresh"
        onClick={() => window.location.reload()}
      >
        새로고침
      </button>
    </div>
  );
}