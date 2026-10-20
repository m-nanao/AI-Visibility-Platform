import { NextResponse } from "next/server";
import { HISTORY_READ_TOKEN_HEADER } from "../../lib/analysis-history";
import { getServerSupabaseAccessToken } from "../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's GET /tags (see
 * backend/main.py's list_tags_endpoint() — feature/history-tags-
 * categories). Mirrors app/api/analysis-runs/route.ts's GET handler
 * exactly: both JWT and HISTORY_READ_TOKEN are accepted (backend uses
 * the same `_resolve_history_access()` gate GET /analysis-runs does),
 * so this stays compatible with every existing caller of the read
 * endpoints. In JWT mode the backend always scopes the result to the
 * caller's accessible projects — this route never has to do that
 * itself, it only forwards the optional `projectId` narrower.
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
  const projectId = searchParams.get("projectId");
  const forwardedParams = new URLSearchParams();
  if (projectId !== null) {
    forwardedParams.set("projectId", projectId);
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
      `${baseUrl.replace(/\/$/, "")}/tags?${forwardedParams.toString()}`,
      { headers },
    );
  } catch {
    console.warn("[tags] Python API GET request failed");
    return NextResponse.json(
      { error: "タグ一覧を読み込めませんでした。" },
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
    console.warn(`[tags] Python API GET returned HTTP ${response.status}`);
    return NextResponse.json(
      { error: "タグ一覧を読み込めませんでした。" },
      { status: 502 },
    );
  }

  const json = await response.json().catch(() => null);
  if (json === null) {
    console.warn("[tags] Python API GET returned invalid JSON");
    return NextResponse.json(
      { error: "タグ一覧を読み込めませんでした。" },
      { status: 502 },
    );
  }

  return NextResponse.json(json);
}

/**
 * Thin proxy to the Python analysis API's POST /tags — unlike GET
 * above, this is JWT-only with no HISTORY_READ_TOKEN fallback of any
 * kind (mirrors app/api/analysis-jobs/route.ts's POST handler exactly
 * — same reasoning: the Python API's own `_resolve_tag_category_auth()`
 * never even looks at X-History-Read-Token, so attaching it here would
 * be dead weight, not a real fallback). 400/401/403/409 are all
 * forwarded as-is — every one is already a safe, hardcoded, short
 * error string on the Python API side.
 */
export async function POST(request: Request) {
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

  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/tags`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    console.warn("[tags] Python API POST request failed");
    return NextResponse.json({ error: "タグの作成に失敗しました。" }, { status: 503 });
  }

  if (
    response.status === 400 ||
    response.status === 401 ||
    response.status === 403 ||
    response.status === 409 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string" ? errorBody.error : "タグの作成に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[tags] Python API POST returned HTTP ${response.status}`);
    return NextResponse.json({ error: "タグの作成に失敗しました。" }, { status: 502 });
  }

  const json = await response.json().catch(() => null);
  if (json === null) {
    console.warn("[tags] Python API POST returned invalid JSON");
    return NextResponse.json({ error: "タグの作成に失敗しました。" }, { status: 502 });
  }

  return NextResponse.json(json, { status: 201 });
}
