const handlers = new Set<(raw: string) => void>();
let es: EventSource | null = null;

function ensureStream() {
  if (es) return;
  es = new EventSource("/api/notifications/stream");
  es.onmessage = (event) => {
    for (const h of handlers) h(event.data);
  };
  es.onerror = () => {};
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
