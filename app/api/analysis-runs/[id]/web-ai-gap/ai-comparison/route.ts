import { NextResponse } from "next/server";
import { HISTORY_READ_TOKEN_HEADER } from "../../../../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's POST
 * /analysis-runs/{id}/web-ai-gap/ai-comparison (see backend/main.py's
 * generate_web_ai_gap_ai_comparison(),
 * services/ai_gap_comparison.py) — generates an AI-powered comparison
 * of a saved analysis run's Web excerpt and AI observation summaries,
 * on demand from the history detail screen. Mirrors
 * app/api/analysis-runs/[id]/rerun/gemini/route.ts's POST handler: same
 * PYTHON_ANALYSIS_API_URL/HISTORY_READ_TOKEN/Authorization forwarding,
 * same 503/403/404 passthrough.
 *
 * A 502 or 503 here both mean nothing was generated or saved — the
 * Python API's `error` message is forwarded as-is (it is always a
 * short, safe-to-display reason, never an API key/token) — 503 means
 * the comparison was never even attempted (e.g. Anthropic API key not
 * configured, or the existing simple judgement isn't usable as input),
 * 502 means the Anthropic call was attempted and failed.
 */
export async function POST(
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
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/web-ai-gap/ai-comparison`,
      { method: "POST", headers },
    );
  } catch {
    console.warn("[analysis-runs/[id]/web-ai-gap/ai-comparison] Python API request failed");
    return NextResponse.json(
      { error: "AI差分比較の生成に失敗しました。" },
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

  if (response.status === 502) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "AI差分比較の生成に失敗しました。";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  if (!response.ok) {
    console.warn(
      `[analysis-runs/[id]/web-ai-gap/ai-comparison] Python API returned HTTP ${response.status}`,
    );
    return NextResponse.json(
      { error: "AI差分比較の生成に失敗しました。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn(
      "[analysis-runs/[id]/web-ai-gap/ai-comparison] Python API returned invalid JSON",
    );
    return NextResponse.json(
      { error: "AI差分比較の生成に失敗しました。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}
