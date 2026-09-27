import { useSyncExternalStore } from "react";
import type { StreamStatus } from "./notificationStream";

// 페이지가 es.onmessage/onerror 프로퍼티를 직접 지정해도 충돌하지 않도록
// addEventListener로 구독한다. EventSource는 끊기면 자동으로 재연결하며,
// 재연결에 성공하면 다시 'open' 이벤트를 발생시킨다.
//
// 모듈 단위로 "현재 페이지의 실시간 스트림" 하나만 추적한다. 화면엔
// 타임라인/게시글 페이지가 한 번에 하나만 떠 있으므로 전역 싱글턴으로 충분하다.
let currentStream: EventSource | null = null;
let currentStatus: StreamStatus = "open";
const listeners = new Set<() => void>();

function setStatus(status: StreamStatus) {
  currentStatus = status;
  for (const l of listeners) l();
}

export function trackStream(es: EventSource) {
  if (currentStream === es) return;
  if (currentStream) untrackStream(currentStream);
  currentStream = es;
  currentStatus = "open";
  es.addEventListener("open", onOpen);
  es.addEventListener("error", onError);
}

export function untrackStream(es: EventSource) {
  if (currentStream !== es) return;
  es.removeEventListener("open", onOpen);
  es.removeEventListener("error", onError);
  currentStream = null;
}

function onOpen() {
  setStatus("open");
}

function onError() {
  setStatus("down");
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function getSnapshot(): StreamStatus {
  return currentStatus;
}

export function useLiveStreamStatus(): StreamStatus {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}