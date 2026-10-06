import { NextResponse } from "next/server";
import { HISTORY_READ_TOKEN_HEADER } from "../../../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's PATCH
 * /analysis-runs/{id}/important (see backend/main.py's
 * set_analysis_run_important(), services/analysis_history_repository.py's
 * set_analysis_run_important() — DB design 案A,
 * docs/38_history_marking_design.md). Mirrors
 * app/api/analysis-runs/[id]/route.ts's GET/DELETE handlers and
 * app/api/analysis-runs/[id]/rerun/gemini/route.ts's POST handler: same
 * PYTHON_ANALYSIS_API_URL/HISTORY_READ_TOKEN/Authorization forwarding,
 * same 503/403/404 passthrough. Unlike those two, this endpoint takes a
 * request body (`{"isImportant": boolean}`), forwarded through as-is —
 * the Python API is the source of truth for validating it.
 */
export async function PATCH(
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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid request body" }, { status: 400 });
  }

  const historyReadToken = process.env.HISTORY_READ_TOKEN;
  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(historyReadToken ? { [HISTORY_READ_TOKEN_HEADER]: historyReadToken } : {}),
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/important`,
      { method: "PATCH", headers, body: JSON.stringify(body) },
    );
  } catch {
    console.warn("[analysis-runs/[id]/important] Python API request failed");
    return NextResponse.json(
      { error: "重要フラグの更新に失敗しました。" },
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

  if (response.status === 400) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "invalid request body";
    return NextResponse.json({ error: message }, { status: 400 });
  }

  if (!response.ok) {
    console.warn(
      `[analysis-runs/[id]/important] Python API returned HTTP ${response.status}`,
    );
    return NextResponse.json(
      { error: "重要フラグの更新に失敗しました。" },
      { status: 502 },
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    console.warn("[analysis-runs/[id]/important] Python API returned invalid JSON");
    return NextResponse.json(
      { error: "重要フラグの更新に失敗しました。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}
