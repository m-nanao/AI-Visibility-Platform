import { NextResponse } from "next/server";
import { parseAnalysisRunListResponse } from "../../lib/analysis-history-schema";
import { HISTORY_READ_TOKEN_HEADER } from "../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../lib/supabase/server";

// Mirrors backend/services/analysis_history_repository.py's
// DEFAULT_LIST_LIMIT (20) and offset default (0) — kept in sync
// manually since this is a thin proxy, not a shared package.
const DEFAULT_LIMIT = "20";
const DEFAULT_OFFSET = "0";

/**
 * Thin proxy to the Python analysis API's GET /analysis-runs, mirroring
 * app/api/analyze/route.ts's PYTHON_ANALYSIS_API_URL usage. Read-only —
 * this route never calls POST /analyze or writes anything.
 *
 * Response shapes returned to the caller:
 * - 200: the Python API's AnalysisRunListResponse, validated with Zod.
 * - 503: history read is disabled or unconfigured — either because
 *   PYTHON_ANALYSIS_API_URL itself is unset here, or because the
 *   Python API returned 503 (READ_HISTORY_ENABLED=false, DATABASE_URL
 *   unset, HISTORY_READ_TOKEN unset, or a DB connection/query failure —
 *   see backend/main.py's GET /analysis-runs). The Python API's own
 *   `error` message is forwarded as-is; it is always a short, safe,
 *   hardcoded string (see backend/services/analysis_history_repository.py),
 *   never raw connection details.
 * - 403: the HISTORY_READ_TOKEN gate rejected the request (see
 *   docs/24_auth_rls_history_access_design.md "7. backend APIでの
 *   アクセス制御案") — forwarded as-is.
 * - 502: the Python API responded with something else unexpected
 *   (non-2xx, invalid JSON, or a body that fails schema validation).
 *
 * Attaches HISTORY_READ_TOKEN (a server-side-only env var — never
 * NEXT_PUBLIC_*) as the X-History-Read-Token header when set, so the
 * browser never sees or sends it; when unset, the Python API's own
 * "token is not configured" 503 is what the caller sees. This remains
 * the only header the Python API's GET /analysis-runs actually checks
 * (see backend/main.py's _check_history_read_access()) — the
 * Authorization header below is forwarded ahead of the backend
 * actually verifying JWTs against it (docs/32_backend_jwt_verification_design.md
 * "15. project権限判定の実装状況"), so its presence or absence changes
 * nothing about this route's behavior yet.
 *
 * Also attaches the caller's Supabase Auth access token (if a session
 * cookie is present) as `Authorization: Bearer <token>` — see
 * app/lib/supabase/server.ts. Never logged, never included in this
 * route's own response, never put in a URL.
 */
export async function GET(request: Request) {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis history read API is not configured" },
      { status: 503 },
    );
  }

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get("limit") ?? DEFAULT_LIMIT;
  const offset = searchParams.get("offset") ?? DEFAULT_OFFSET;

  const historyReadToken = process.env.HISTORY_READ_TOKEN;
  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    ...(historyReadToken ? { [HISTORY_READ_TOKEN_HEADER]: historyReadToken } : {}),
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
      { headers },
    );
  } catch {
    console.warn("[analysis-runs] Python API request failed");
    return NextResponse.json(
      { error: "分析履歴を読み込めませんでした。" },
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

  if (!response.ok) {
    console.warn(
      `[analysis-runs] Python API returned HTTP ${response.status}`,
    );
    return NextResponse.json(
      { error: "分析履歴を読み込めませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-runs] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "分析履歴を読み込めませんでした。" },
      { status: 502 },
    );
  }

  const parsed = parseAnalysisRunListResponse(json);
  if (!parsed.success) {
    console.warn(
      `[analysis-runs] Python API response failed schema validation (${parsed.reason})`,
    );
    return NextResponse.json(
      { error: "分析履歴を読み込めませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(parsed.data);
}
