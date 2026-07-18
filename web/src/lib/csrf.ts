function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

if (typeof window !== "undefined") {
  const originalFetch = window.fetch;
  window.fetch = function (input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const method = (init?.method || (typeof input === "string" ? input : input instanceof Request ? input.method : "GET")).toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      const csrf = getCsrfToken();
      if (csrf) {
        const headers = new Headers(init?.headers);
        if (!headers.has("X-CSRF-Token")) {
          headers.set("X-CSRF-Token", csrf);
        }
        init = { ...init, headers };
      }
    }
    return originalFetch.call(this, input, init);
  };
}
