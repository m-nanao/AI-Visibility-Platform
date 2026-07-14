import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { timingSafeEqual } from "node:crypto";
import { STAGING_COOKIE_NAME, hashAccessCode } from "./app/lib/staging-auth";

// Least-effort protection for the months-long staging deployment (Vercel),
// not a real auth system — see docs/09_deployment.md "簡易パスコードガード".
// `middleware.ts` is deprecated in this Next.js version in favor of
// `proxy.ts` (defaults to the Node.js runtime, so node:crypto is safe here).
const PUBLIC_PATHS = ["/staging-login", "/api/staging-auth"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
}

function hasValidCookie(
  cookieValue: string | undefined,
  accessCode: string,
): boolean {
  if (!cookieValue) return false;
  const expected = Buffer.from(hashAccessCode(accessCode));
  const actual = Buffer.from(cookieValue);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function proxy(request: NextRequest) {
  const accessCode = process.env.STAGING_ACCESS_CODE;

  // Not configured (local dev, or a deploy that hasn't opted in) -> no gate.
  // This deployment is also the only place metadata.robots sets noindex, so
  // the X-Robots-Tag header below is added unconditionally as a second,
  // header-level signal for crawlers that ignore the HTML meta tag.
  if (!accessCode) {
    const response = NextResponse.next();
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
    return response;
  }

  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    const response = NextResponse.next();
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
    return response;
  }

  const cookie = request.cookies.get(STAGING_COOKIE_NAME)?.value;
  if (hasValidCookie(cookie, accessCode)) {
    const response = NextResponse.next();
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
    return response;
  }

  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { error: "staging environment: passcode required" },
      { status: 401, headers: { "X-Robots-Tag": "noindex, nofollow" } },
    );
  }

  const loginUrl = new URL("/staging-login", request.url);
  loginUrl.searchParams.set("next", pathname);
  const response = NextResponse.redirect(loginUrl);
  response.headers.set("X-Robots-Tag", "noindex, nofollow");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
