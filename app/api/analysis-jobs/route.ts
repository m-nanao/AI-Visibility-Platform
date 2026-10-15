import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's POST /analysis-jobs (see
 * backend/main.py, docs/40_async_analysis_jobs_design.md "7.1") — the
 * Phase 3 counterpart to app/api/analyze/route.ts, but deliberately
 * much simpler: this route only waits for job *acceptance* (202), not
 * for the analysis itself to finish, so there is no
 * PYTHON_API_TIMEOUT_MS/AbortController/dummy-fallback concern here at
 * all — unlike /api/analyze, a communication failure here is always
 * surfaced as an error, never silently replaced with a fabricated
 * result (docs/40 Phase 3 task's "通信失敗時に架空の分析結果を作らない").
 *
 * Response shapes returned to the caller:
 * - 202: the Python API's AnalysisJobAcceptedResponse, forwarded as-is
 *   (not re-validated with Zod here — app/lib/analysis-jobs.ts's
 *   resolveCreateAnalysisJobOutcome(), called by the browser directly
 *   against this route's own response, does that).
 * - 400: the submitted brandName/documents/urls/projectId/
 *   idempotencyKey failed validation — forwarded as-is.
 * - 401: no session, or the Python API rejected the JWT.
 * - 403: the caller is not a member of the requested project.
 * - 404: the job API is disabled on the Python API
 *   (ANALYSIS_JOBS_ENABLED=false) — forwarded as-is, since that's
 *   exactly what the Python API itself returns for this case (see
 *   backend/main.py's _resolve_job_auth()).
 * - 409: the same idempotencyKey was already used for different
 *   input.
 * - 429: the project/user queued-job limit was reached.
 * - 503: PYTHON_ANALYSIS_API_URL is unset here, or the request to the
 *   Python API failed outright, or the Python API itself is
 *   unconfigured (JWT verification unavailable).
 * - 502: the Python API responded with something else unexpected.
 *
 * Attaches the caller's Supabase Auth access token as
 * `Authorization: Bearer <token>` when a session cookie is present —
 * see app/lib/supabase/server.ts. Never attaches HISTORY_READ_TOKEN:
 * unlike the existing /api/analysis-runs* proxies, POST
 * /analysis-jobs has no such fallback on the Python API side at all
 * (JWT is strictly required — see backend/main.py's
 * _resolve_job_auth()), so there is nothing here to bypass that
 * requirement with. The request body (which may contain
 * brandName/urls/documents — user-entered text, not secrets) is
 * forwarded as-is and never logged.
 */
export async function POST(request: Request) {
  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis jobs API is not configured" },
      { status: 503 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid request body" }, { status: 400 });
  }

  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/analysis-jobs`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    console.warn("[analysis-jobs] Python API request failed");
    return NextResponse.json(
      { error: "分析を開始できませんでした。" },
      { status: 503 },
    );
  }

  // 400/401/403/404/409/429/503 are all forwarded as-is — every one
  // of these is already a safe, hardcoded, short error string on the
  // Python API side (see backend/main.py's ANALYSIS_JOBS_*_MESSAGE
  // constants), never raw connection details or user input echoed
  // back unexpectedly.
  if (
    response.status === 400 ||
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 409 ||
    response.status === 429 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "分析を開始できませんでした。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[analysis-jobs] Python API returned HTTP ${response.status}`);
    return NextResponse.json(
      { error: "分析を開始できませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-jobs] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "分析を開始できませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json, { status: 202 });
}
