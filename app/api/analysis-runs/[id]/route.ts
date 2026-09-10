import { NextResponse } from "next/server";
import { parseAnalysisRunDetailResponse } from "../../../lib/analysis-history-schema";

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
 * - 404: no analysis run with this id exists — forwarded as-is from
 *   the Python API (backend/main.py's GET /analysis-runs/{id}).
 * - 502: the Python API responded with something else unexpected
 *   (non-2xx other than 404, invalid JSON, or a body that fails
 *   schema validation).
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

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}`,
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
