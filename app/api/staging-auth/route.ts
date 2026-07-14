import { NextResponse } from "next/server";
import {
  STAGING_COOKIE_NAME,
  hashAccessCode,
  sanitizeNextPath,
} from "../../lib/staging-auth";

// Cookie lifetime chosen to comfortably cover the "数ヶ月" (several months)
// intended lifespan of this staging deployment without forcing frequent
// re-entry — see docs/09_deployment.md.
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

export async function POST(request: Request) {
  const url = new URL(request.url);
  const next = sanitizeNextPath(url.searchParams.get("next"));
  const accessCode = process.env.STAGING_ACCESS_CODE;

  const formData = await request.formData().catch(() => null);
  const submitted = formData?.get("code");

  if (
    !accessCode ||
    typeof submitted !== "string" ||
    submitted !== accessCode
  ) {
    const loginUrl = new URL("/staging-login", request.url);
    loginUrl.searchParams.set("error", "1");
    loginUrl.searchParams.set("next", next);
    return NextResponse.redirect(loginUrl, 303);
  }

  const response = NextResponse.redirect(new URL(next, request.url), 303);
  response.cookies.set({
    name: STAGING_COOKIE_NAME,
    value: hashAccessCode(accessCode),
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}
