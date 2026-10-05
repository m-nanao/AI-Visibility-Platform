import { NextResponse } from "next/server";
import { HISTORY_READ_TOKEN_HEADER } from "../../../../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's POST
 * /analysis-runs/{id}/rerun/gemini (see backend/main.py's
 * rerun_gemini_observation(), services/gemini_rerun.py) — re-runs only
 * the Gemini observation for one saved analysis run and persists the
 * updated card in place. Mirrors
 * app/api/analysis-runs/[id]/route.ts's GET/DELETE handlers: same
 * PYTHON_ANALYSIS_API_URL/HISTORY_READ_TOKEN/Authorization forwarding,
 * same 503/403/404 passthrough.
 *
 * A 502 here specifically means the Gemini call itself failed or is
 * disabled (see services/gemini_rerun.py's GeminiRerunOutcome) — the
 * Python API's `error` message is forwarded as-is (it is always a
 * short, safe-to-display reason, never an API key/token) so the
 * history detail page can show the caller something actionable (e.g.
 * "Gemini request limit must be 1.") rather than a generic failure.
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
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/rerun/gemini`,
      { method: "POST", headers },
    );
  } catch {
    console.warn("[analysis-runs/[id]/rerun/gemini] Python API request failed");
    return NextResponse.json(
      { error: "Geminiの再実行に失敗しました。" },
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
        : "Geminiの再実行に失敗しました。";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  if (!response.ok) {
    console.warn(
      `[analysis-runs/[id]/rerun/gemini] Python API returned HTTP ${response.status}`,
    );
    return NextResponse.json(
      { error: "Geminiの再実行に失敗しました。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-runs/[id]/rerun/gemini] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "Geminiの再実行に失敗しました。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}
