import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's GET /analysis-jobs/{id}
 * (see backend/main.py, docs/40_async_analysis_jobs_design.md "7.2") —
 * mirrors app/api/analysis-runs/[id]/route.ts's conventions, but
 * JWT-only like POST /api/analysis-jobs above (no HISTORY_READ_TOKEN
 * fallback of any kind).
 *
 * Response shapes returned to the caller:
 * - 200: the Python API's AnalysisJobStatusResponse, forwarded as-is
 *   (re-validated with Zod by the caller — see
 *   app/lib/analysis-jobs.ts's resolveAnalysisJobStatusOutcome()).
 * - 401: no session, or the Python API rejected the JWT.
 * - 403: the caller does not have access to this job's project — also
 *   returned (deliberately, by the Python API itself) for a job that
 *   doesn't exist at all, so this route cannot be used to probe
 *   whether a given id exists (see
 *   docs/32_backend_jwt_verification_design.md's existence-leak
 *   avoidance, reused here).
 * - 404: the job id exists but has otherwise been excluded (e.g.
 *   soft-deleted) — forwarded as-is.
 * - 404: also returned when the job API is disabled on the Python API
 *   (ANALYSIS_JOBS_ENABLED=false).
 * - 503: PYTHON_ANALYSIS_API_URL is unset here, the request to the
 *   Python API failed outright, or JWT verification is unavailable.
 * - 502: the Python API responded with something else unexpected.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

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
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-jobs/${encodeURIComponent(id)}`,
      { headers },
    );
  } catch {
    console.warn("[analysis-jobs/[id]] Python API request failed");
    return NextResponse.json(
      { error: "分析の状態を確認できませんでした。" },
      { status: 503 },
    );
  }

  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "分析の状態を確認できませんでした。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[analysis-jobs/[id]] Python API returned HTTP ${response.status}`);
    return NextResponse.json(
      { error: "分析の状態を確認できませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-jobs/[id]] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "分析の状態を確認できませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}
