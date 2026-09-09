import { NextResponse } from "next/server";
import { parseAnalysisRunListResponse } from "../../lib/analysis-history-schema";

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
 *   unset, or a DB connection/query failure — see
 *   backend/main.py's GET /analysis-runs). The Python API's own
 *   `error` message is forwarded as-is; it is always a short, safe,
 *   hardcoded string (see backend/services/analysis_history_repository.py),
 *   never raw connection details.
 * - 502: the Python API responded with something else unexpected
 *   (non-2xx, invalid JSON, or a body that fails schema validation).
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

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`,
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
