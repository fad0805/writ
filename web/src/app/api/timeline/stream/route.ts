import http from "http";
import https from "https";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

async function safeClose(writer: WritableStreamDefaultWriter) {
  try { await writer.close(); } catch {}
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const tlType = searchParams.get("type") || "home";
  const apiHost = process.env.API_HOST || "http://localhost:8000";
  const backendUrl = new URL(`${apiHost}/api/timeline/stream?type=${tlType}`);
  const cookie = request.headers.get("cookie") || "";

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const decoder = new TextDecoder();
  let closed = false;

  const httpModule = backendUrl.protocol === "https:" ? https : http;
  let aborted = false;
  const req = httpModule.get(
    backendUrl.toString(),
    { headers: { Cookie: cookie } },
    (res) => {
      if (res.statusCode !== 200) {
        if (!closed) { closed = true; safeClose(writer); }
        return;
      }
      res.on("data", (chunk: Buffer) => {
        if (!aborted) writer.write(decoder.decode(chunk, { stream: true }));
      });
      const cleanup = () => { if (!closed) { closed = true; safeClose(writer); } };
      res.on("end", cleanup);
      res.on("error", cleanup);
    },
  );
  req.on("error", () => { if (!closed) { closed = true; safeClose(writer); } });

  request.signal.addEventListener("abort", () => {
    aborted = true;
    req.destroy();
    safeClose(writer);
  });

  return new Response(readable, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
