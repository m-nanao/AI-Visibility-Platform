import { NextResponse } from "next/server";
import { parseMeProjectsResponse } from "../../../lib/analysis-jobs-schema";
import { getServerSupabaseAccessToken } from "../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's GET /me/projects (see
 * backend/main.py) — mirrors app/api/analysis-runs/route.ts's
 * PYTHON_ANALYSIS_API_URL usage and error-shape conventions.
 *
 * Unlike the existing /api/analysis-runs* proxies, this route never
 * attaches HISTORY_READ_TOKEN — GET /me/projects has no such
 * fallback on the Python API side at all (it is JWT-only, no
 * exceptions — see backend/main.py's _resolve_jwt_only_auth()), so
 * there is nothing here to bypass that requirement with.
 *
 * Response shapes returned to the caller:
 * - 200: the Python API's MeProjectsResponse, validated with Zod.
 * - 401: no session, or the Python API rejected the JWT (expired,
 *   invalid, wrong issuer/audience) — forwarded as-is.
 * - 503: JWT verification itself isn't configured on the Python API,
 *   or PYTHON_ANALYSIS_API_URL is unset here, or the request to the
 *   Python API failed outright.
 * - 502: the Python API responded with something else unexpected.
 *
 * Attaches the caller's Supabase Auth access token (if a session
 * cookie is present) as `Authorization: Bearer <token>` — see
 * app/lib/supabase/server.ts. Never logged, never included in this
 * route's own response, never put in a URL. When there is no session
 * at all, no Authorization header is sent and the Python API's own
 * 401 is what the caller sees.
 */
export async function GET(request: Request) {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis jobs API is not configured" },
      { status: 503 },
    );
  }

  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/me/projects`, { headers });
  } catch {
    console.warn("[me/projects] Python API request failed");
    return NextResponse.json(
      { error: "利用可能なプロジェクトを確認できませんでした。" },
      { status: 503 },
    );
  }

  if (response.status === 401) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string" ? errorBody.error : "authentication required";
    return NextResponse.json({ error: message }, { status: 401 });
  }

  if (response.status === 503) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "analysis jobs API is not configured";
    return NextResponse.json({ error: message }, { status: 503 });
  }

  if (!response.ok) {
    console.warn(`[me/projects] Python API returned HTTP ${response.status}`);
    return NextResponse.json(
      { error: "利用可能なプロジェクトを確認できませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[me/projects] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "利用可能なプロジェクトを確認できませんでした。" },
      { status: 502 },
    );
  }

  const parsed = parseMeProjectsResponse(json);
  if (!parsed.success) {
    console.warn(`[me/projects] Python API response failed schema validation (${parsed.reason})`);
    return NextResponse.json(
      { error: "利用可能なプロジェクトを確認できませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(parsed.data);
}
