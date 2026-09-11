import { NextResponse } from "next/server";
import { parseAnalysisRunDetailResponse } from "../../../lib/analysis-history-schema";
import { HISTORY_READ_TOKEN_HEADER } from "../../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's GET /analysis-runs/{id},
 * mirroring app/api/analysis-runs/route.ts's PYTHON_ANALYSIS_API_URL
 * usage and error-shape conventions.
 *
 * Response shapes returned to the caller:
 * - 200: the Python API's AnalysisRunDetailResponse, validated with Zod
 *   (the envelope only — `result`'s inner AnalysisResult shape is
 *   validated separately at the page level, see
 *   app/lib/analysis-history.ts's resolveHistoryDetailFetchOutcome()).
 * - 503: history read is disabled or unconfigured — same meaning as
 *   the list endpoint (see app/api/analysis-runs/route.ts).
 * - 403: the HISTORY_READ_TOKEN gate rejected the request — forwarded
 *   as-is (see docs/24_auth_rls_history_access_design.md "7. backend
 *   APIでのアクセス制御案").
 * - 404: no analysis run with this id exists — forwarded as-is from
 *   the Python API (backend/main.py's GET /analysis-runs/{id}).
 * - 502: the Python API responded with something else unexpected
 *   (non-2xx other than 404, invalid JSON, or a body that fails
 *   schema validation).
 *
 * Attaches HISTORY_READ_TOKEN (a server-side-only env var — never
 * NEXT_PUBLIC_*) as the X-History-Read-Token header when set, so the
 * browser never sees or sends it; when unset, the Python API's own
 * "token is not configured" 503 is what the caller sees. This remains
 * the only header the Python API actually checks — see
 * app/api/analysis-runs/route.ts's docstring for why the Authorization
 * header below doesn't change this route's behavior yet.
 *
 * Also attaches the caller's Supabase Auth access token (if a session
 * cookie is present) as `Authorization: Bearer <token>` — see
 * app/lib/supabase/server.ts. Never logged, never included in this
 * route's own response, never put in a URL.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis history read API is not configured" },
      { status: 503 },
    );
  }

  const historyReadToken = process.env.HISTORY_READ_TOKEN;
  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    ...(historyReadToken ? { [HISTORY_READ_TOKEN_HEADER]: historyReadToken } : {}),
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}`,
      { headers },
    );
  } catch {
    console.warn("[analysis-runs/[id]] Python API request failed");
    return NextResponse.json(
      { error: "分析履歴の詳細を読み込めませんでした。" },
      { status: 503 },
    );
  }

  if (response.status === 503) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "analysis history read API is not enabled";
    return NextResponse.json({ error: message }, { status: 503 });
  }

  if (response.status === 403) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "analysis history read access denied";
    return NextResponse.json({ error: message }, { status: 403 });
  }

  if (response.status === 404) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "analysis run not found";
    return NextResponse.json({ error: message }, { status: 404 });
  }

  if (!response.ok) {
    console.warn(
      `[analysis-runs/[id]] Python API returned HTTP ${response.status}`,
    );
    return NextResponse.json(
      { error: "分析履歴の詳細を読み込めませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-runs/[id]] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "分析履歴の詳細を読み込めませんでした。" },
      { status: 502 },
    );
  }

  const parsed = parseAnalysisRunDetailResponse(json);
  if (!parsed.success) {
    console.warn(
      `[analysis-runs/[id]] Python API response failed schema validation (${parsed.reason})`,
    );
    return NextResponse.json(
      { error: "分析履歴の詳細を読み込めませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(parsed.data);
}
