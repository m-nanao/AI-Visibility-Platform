import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's POST
 * /analysis-runs/{id}/tags (attach one tag to one run — see
 * backend/main.py's attach_tag_endpoint(),
 * feature/history-tags-categories). JWT-only, no HISTORY_READ_TOKEN
 * fallback — mirrors app/api/tags/route.ts's POST handler.
 *
 * On success the Python API returns 204 No Content — this route
 * forwards that exact status with an empty body, and deliberately
 * never calls `response.json()` on it (a 204 has no body; parsing it
 * as JSON would throw — this task's explicit "空レスポンスをJSONとして
 * 解析してエラーにしない" requirement).
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
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/tags`,
      { method: "POST", headers, body: JSON.stringify(body) },
    );
  } catch {
    console.warn("[analysis-runs/[id]/tags] Python API POST request failed");
    return NextResponse.json({ error: "タグの追加に失敗しました。" }, { status: 503 });
  }

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  if (
    response.status === 400 ||
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 409 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string" ? errorBody.error : "タグの追加に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  console.warn(`[analysis-runs/[id]/tags] Python API POST returned HTTP ${response.status}`);
  return NextResponse.json({ error: "タグの追加に失敗しました。" }, { status: 502 });
}
