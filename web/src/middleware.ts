import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // /@username → /profile/username
  const userMatch = pathname.match(/^\/@([^/]+)$/);
  if (userMatch) {
    return NextResponse.rewrite(new URL(`/profile/${userMatch[1]}`, request.url));
  }

  // /@username/series/number → /novels/by-number/username/number
  const seriesMatch = pathname.match(/^\/@([^/]+)\/series\/([^/]+)$/);
  if (seriesMatch) {
    return NextResponse.rewrite(new URL(`/novels/by-number/${seriesMatch[1]}/${seriesMatch[2]}`, request.url));
  }

  // /@username/number → /post/by-number/username/number
  const postMatch = pathname.match(/^\/@([^/]+)\/([^/]+)$/);
  if (postMatch) {
    return NextResponse.rewrite(new URL(`/post/by-number/${postMatch[1]}/${postMatch[2]}`, request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/(.*)"],
};
