import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's GET
 * /analysis-jobs/{id}/result (see backend/main.py,
 * docs/40_async_analysis_jobs_design.md "7.3"/"13.2") — same
 * conventions as app/api/analysis-jobs/[id]/route.ts above.
 *
 * Response shapes returned to the caller:
 * - 200: the Python API's AnalysisJobResultResponse, forwarded as-is.
 *   Re-validated with Zod by the caller
 *   (app/lib/analysis-jobs.ts's resolveAnalysisJobResultOutcome()),
 *   which also distinguishes a "failed" job (200, no `result`) from a
 *   genuinely successful one and never treats the backend's
 *   placeholder `result_json={}` as a real result.
 * - 401/403/404/503/502: same meaning as
 *   app/api/analysis-jobs/[id]/route.ts.
 * - 409: the job hasn't finished yet (queued/running) — there is no
 *   result-shaped body to return; forwarded as-is so the caller can
 *   show a "still processing" message distinct from an actual error.
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
      `${baseUrl.replace(/\/$/, "")}/analysis-jobs/${encodeURIComponent(id)}/result`,
      { headers },
    );
  } catch {
    console.warn("[analysis-jobs/[id]/result] Python API request failed");
    return NextResponse.json(
      { error: "分析結果を確認できませんでした。" },
      { status: 503 },
    );
  }

  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 409 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "分析結果を確認できませんでした。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[analysis-jobs/[id]/result] Python API returned HTTP ${response.status}`);
    return NextResponse.json(
      { error: "分析結果を確認できませんでした。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-jobs/[id]/result] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "分析結果を確認できませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}
