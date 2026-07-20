import { NextRequest, NextResponse } from "next/server";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

export default function middleware(request: NextRequest) {
  const accept = request.headers.get("accept") || "";
  const { pathname } = request.nextUrl;

  // ActivityPub JSON 요청 → API로 프록시
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

  return NextResponse.next();
}

export const config = {
  matcher: ["/@:username/:number?", "/@:username"],
};
