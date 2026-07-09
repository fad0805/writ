import http from "http";
import https from "https";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const apiHost = process.env.API_HOST || "http://localhost:8000";
  const backendUrl = new URL(`${apiHost}/api/notifications/stream`);
  const cookie = request.headers.get("cookie") || "";

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const decoder = new TextDecoder();

  const httpModule = backendUrl.protocol === "https:" ? https : http;
  let aborted = false;
  const req = httpModule.get(
    backendUrl.toString(),
    { headers: { Cookie: cookie } },
    (res) => {
      if (res.statusCode !== 200) {
        writer.close();
        return;
      }
      res.on("data", (chunk: Buffer) => {
        if (!aborted) writer.write(decoder.decode(chunk, { stream: true }));
      });
      res.on("end", () => writer.close());
      res.on("error", () => writer.close());
    },
  );
  req.on("error", () => writer.close());

  request.signal.addEventListener("abort", () => {
    aborted = true;
    req.destroy();
    writer.close().catch(() => {});
  });

  return new Response(readable, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
