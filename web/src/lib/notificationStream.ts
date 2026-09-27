import { useSyncExternalStore } from "react";

export type StreamStatus = "open" | "down";

const handlers = new Set<(raw: string) => void>();
const statusHandlers = new Set<() => void>();
let es: EventSource | null = null;
let currentStatus: StreamStatus = "open";

function setStatus(status: StreamStatus) {
  if (status === currentStatus) return;
  currentStatus = status;
  for (const h of statusHandlers) h();
}

function ensureStream() {
  if (es) return;
  es = new EventSource("/api/notifications/stream");
  es.onmessage = (event) => {
    for (const h of handlers) h(event.data);
  };
  es.onerror = () => setStatus("down");
  es.onopen = () => setStatus("open");
}

export function onNotificationStream(cb: (raw: string) => void): () => void {
  ensureStream();
  handlers.add(cb);
  return () => {
    handlers.delete(cb);
    if (handlers.size === 0) {
      es?.close();
      es = null;
    }
  };
}

function subscribeStatus(cb: () => void) {
  ensureStream();
  statusHandlers.add(cb);
  return () => {
    statusHandlers.delete(cb);
  };
}

function getStatus(): StreamStatus {
  return currentStatus;
}

export function useNotificationStreamStatus(): StreamStatus {
  return useSyncExternalStore(subscribeStatus, getStatus, getStatus);
}