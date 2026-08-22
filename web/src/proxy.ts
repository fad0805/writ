import { NextRequest, NextResponse } from "next/server";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

// 요청마다 nonce를 발급해 문서 응답의 CSP에 물린다.
// Next.js는 요청 헤더의 Content-Security-Policy에서 nonce를 읽어 자체
// 부트스트랩 스크립트에 자동 적용하고, 레이아웃의 수제 인라인 스크립트는
// x-nonce 헤더를 읽어 직접 넣는다(web/src/app/layout.tsx).

function buildCsp(nonce: string, isDev: boolean): string {
  // 개발 모드에서는 React Refresh/HMR 때문에 unsafe-eval/inline이 필요하다.
  const scriptSrc = isDev ? "'self' 'unsafe-inline' 'unsafe-eval'" : `'self' 'nonce-${nonce}' 'strict-dynamic'`;
  const connectSrc = isDev ? "'self' http://localhost:* ws://localhost:*" : "'self'";
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    // 인라인 스타일 속성은 허용 유지(React의 style={} 사용 패턴과의 충돌 방지).
    // CSSOM 조작은 막히지 않으므로 실익 대비 회귀 위험이 큼.
    "style-src 'self' 'unsafe-inline'",
    // 연합(federation) 콘텐츠 특성상 임의 서버의 이미지/미디어가 본문에 섞인다.
    // 수동 콘텐츠(passive)이므로 https:/http: 허용 유지.
    "img-src 'self' data: blob: https: http:",
    "media-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const accept = request.headers.get("accept") || "";
  const { pathname } = request.nextUrl;

  // ActivityPub JSON 요청 → API로 프록시 (봇 대상 응답이라 CSP 불필요)
  if (accept.includes("application/activity+json") || accept.includes("application/ld+json")) {
    // /@username/:number → API의 ActivityPub post
    if (pathname.match(/^\/@[\w-]+\/[\w-]+$/)) {
      return NextResponse.rewrite(new URL(`${API_HOST}/api/by-number/${pathname.slice(2)}`, request.url));
    }
    // /@username → API의 Actor (main.py: /users/{username})
    if (pathname.match(/^\/@[\w-]+$/)) {
      return NextResponse.rewrite(new URL(`${API_HOST}/users/${pathname.slice(2)}`, request.url));
    }
  }

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const nonce = btoa(String.fromCharCode(...bytes));
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    // 정적 에셋/백엔드 프록시 경로는 제외: 문서(HTML) 응답에만 CSP가 필요하다.
    "/((?!api|_next/static|_next/image|favicon.ico|sw.js|manifest.json|robots.txt|.well-known|static|uploads|emojis).*)",
  ],
};
